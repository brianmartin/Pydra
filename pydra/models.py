"""
    Copyright 2009 Oregon State University

    This file is part of Pydra.

    Pydra is free software: you can redistribute it and/or modify
    it under the terms of the GNU General Public License as published by
    the Free Software Foundation, either version 3 of the License, or
    (at your option) any later version.

    Pydra is distributed in the hope that it will be useful,
    but WITHOUT ANY WARRANTY; without even the implied warranty of
    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
    GNU General Public License for more details.

    You should have received a copy of the GNU General Public License
    along with Pydra.  If not, see <http://www.gnu.org/licenses/>.
"""
from __future__ import with_statement

from threading import Lock
import time

from django.db import models
import simplejson

class Node(models.Model):
    """
    Represents a node in the cluster
    """
    host            = models.CharField(max_length=255)
    port            = models.IntegerField(default=11890)
    cores_available = models.IntegerField(null=True)
    cores           = models.IntegerField(null=True)

    # key given to node for use by its workers
    key             = models.CharField(max_length=50, null=True)

    # keys used by master to connect to the node
    # this keypair is generated by the Master, the private key
    # is passed to the Node the first time it sees it.
    pub_key         = models.TextField(null=True)

    stones          = models.IntegerField(null=True)
    total_memory    = models.IntegerField(null=True)
    avail_memory    = models.IntegerField(null=True)
    seen            = models.IntegerField(default=False)
    deleted         = models.BooleanField(default=False)

    # non-model fields
    ref             = None
    _info           = None
    pub_key_obj     = None

    def __str__(self):
        return '%s:%s' % (self.host, self.port)

    def status(self):
        ret = 1 if self.ref else 0
        return ret

    class Meta:
        permissions = (
            ("can_edit_nodes", "Can create and edit nodes"),
        )

    def json_safe(self):
        return self.__dict__

    def load_pub_key(self):
        """
        Load public key object from raw data stored in the model
        """
        if self.pub_key_obj:
            return self.pub_key_obj

        elif not self.pub_key:
            return None

        else:
            from django.utils import simplejson
            from Crypto.PublicKey import RSA

            pub_raw = simplejson.loads(self.pub_key)
            pub = [long(x) for x in pub_raw]
            pub_key_obj = RSA.construct(pub)
            self.pub_key_obj = pub_key_obj

            return  pub_key_obj


class TaskInstanceManager(models.Manager):
    """
    Custom manager overridden to supply pre-made queryset for queued and running
    tasks
    """
    def queued(self):
        return self.filter(status=None, started=None)

    def running(self):
        return self.filter(status=None).exclude(started=None)


class AbstractJob(models.Model):
    """
    Encapsulates work that runs on a worker.
    
    task_key:      Key that identifies the code to be run
    subtask_key:   Path within the task that identifies the child task to run
    args:          Dictionary of arguments passed to the task    
    started:       Datetime when this task instance was started
    completed:     Datetime when this task instance completed successfully or 
                   failed
    worker:        Identifier for the worker that ran this task
    status:        Current Status of the task instance
    log_retrieved: Was the logfile retrieved from the remote worker
    """
    task_key        = models.CharField(max_length=255)
    subtask_key     = models.CharField(max_length=255, null=True)
    args            = models.TextField(null=True)
    started         = models.DateTimeField(null=True)
    completed       = models.DateTimeField(null=True)
    worker          = models.CharField(max_length=255, null=True)
    status          = models.IntegerField(null=True)
    log_retrieved   = models.BooleanField(default=False)
    on_main_worker  = True
        
    def __init__(self, *eargs, **kwargs):
        super(AbstractJob, self).__init__(*eargs, **kwargs)

    def __repr__(self):
        return self.__str__()

    def __str__(self):
        return 'root=%s task=%s subtask=%s' % (self.task_id, self.task_key, \
                                               self.subtask_key)
        
    def __unicode__(self):
        return self.__str__()

    class Meta:
        abstract = True


class TaskInstance(AbstractJob):
    """
    Represents and instance of a Task.  This is used to track when a Task was 
    run and whether it completed.

    queued:        Datetime when this task instance was queued
    """
    queued  = models.DateTimeField(auto_now_add=True)
    results_json = models.TextField(null=True)
    results = None
    objects = TaskInstanceManager()
    workunit = None #not used, included for compatibility with WorkUnit
    
    def __init__(self, *eargs, **kw):
        super(TaskInstance, self).__init__(*eargs, **kw) 
        # scheduling-related
        self.priority         = 5
        self.running_workers  = [] # running workers keys (excluding the main worker)
        self.waiting_workers  = [] # workers waiting for more workunits
        self.last_succ_time   = None # when this task last time gets a worker
        self._worker_requests = [] # List of WorkUnit objects
        self.local_workunit   = None # a workunit executed by main worker
    
        # others
        self._request_lock = Lock()
        
        if self.results_json:
            self.results = simplejson.loads(self.results_json)

    def save(self, *args, **kwargs):
        if self.results:
            self.results_json = simplejson.dumps(self.results)
        super(TaskInstance, self).save(*args, **kwargs)

    def __getattribute__(self, key):
        if key == 'task_id':
            return self.id
        elif key == 'task_instance':
            return self
        return super(TaskInstance, self).__getattribute__(key)

    
    def get_batch(self, size=5):
        """
        Gets a batch approximatly the size requested.  Batches may consist
        of individual workunits or slices containing multiple workunits.  Slices
        are not guarunteed to match the requested size, and report an appoximate
        size, so actual batch size can only be approximated.
        
        Workunits are stored as a dictionary of lists.  The keys for each list
        are composed of the values common to other subtasks.  The lists contain
        the unique values.
        """
        job = self.poll_worker_request()
        # if this is the TaskInstance, or only a single workunit, just
        # return it.  It will be faster to deal with just that object
        if job == self or len(self._worker_requests)==1:
            return self.pop_worker_request()
        
        count = 0
        workunits = []
        while job and count < size:
            # batches are only allowed to exceed the batch size by 25% unless
            # there are no slices in the batch.  If the limit has been exceeded
            # break and return the current batch.
            if job.size > (size-count)+(size/4) and count:
                break
            workunits.append(job)
            count += job.size
            self.pop_worker_request()
            job = self.poll_worker_request()
        batch = Batch(workunits)
        batch.args = self.args
        batch.task_instance = self
        batch.size = count

        #add batch relation to all workunits
        for workunit in workunits:
            workunit.batch = batch
            workunit.save()

        batch.subtask_key = workunits[0].subtask_key
        return batch
    
    def transmitable(self):
        return None

    def compute_score(self):
        """
        Computes a priority score for this task, which will be used by the
        scheduler.

        Empirical analysis may reveal a good calculation formula. But in
        general, the following guideline is useful:
        1) Stopped tasks should have higher scores. At least for the current
           design, a task can well proceed even with only one worker. So 
           letting a stopped task run ASAP makes sense.
        2) A task with higher priority should obviously have a higher score.
        3) A task that has been out of worker supply for a long time should
           have a relatively higher score.
        """
        return (self.priority, self.queued)

    def json_safe(self):
        """
        return object as a dictionary of json safe values.  This is needed
        because some complex types like Datetime will cause an exception if
        you attempt to serialize them with simplejson
        """        
        return {
            'id':self.id,
            'task_key':self.task_key,
            'status':self.status,
            'args':self.args,
            'queued':self.queued.strftime('%Y-%m-%d %H:%m:%S') \
                                                    if self.queued else None,
            'started':self.started.strftime('%Y-%m-%d %H:%m:%S') \
                                                    if self.started else None,
            'completed':self.completed.strftime('%Y-%m-%d %H:%m:%S') \
                                                    if self.completed else None,
            'results':self.results
        }

    def queue_worker_request(self, request):
        """
        A worker request is a tuple of:
        (requesting_worker_key, args, subtask_key, workunit_key).
        """
        with self._request_lock:
            self._worker_requests.append(request)

    def pop_worker_request(self):
        """
        A worker request is a tuple of:
        (requesting_worker_key, args, subtask_key, workunit_key).
        """
        with self._request_lock:
            try:
                return self._worker_requests.pop(0)
            except IndexError:
                return None

    def poll_worker_request(self):
        """
        Returns the first worker request in the queue without removing
        it.
        """
        with self._request_lock:
            try:
                return self._worker_requests[0]
            except IndexError:
                return None

    def __str__(self):
        return 'TaskInstance: %s' % self.json_safe()

    class Meta:
        permissions = (
            ("can_run", "Can run tasks on the cluster"),
            ("can_stop_all", "Can stop anyone's tasks")
        )


class WorkUnit(AbstractJob):
    """
    Workunits are subtask requests that can be distributed by pydra.  A
    workunit is generally the smallest unit of work for a task.  This
    model represents key data points about them.
    
    workunit:  key that uniquely identifies this workunit within the 
                datasource for the task.  This might also be the data itself
                depending on how the key was initialized
    """
    task_instance = models.ForeignKey(TaskInstance, related_name='workunits')
    workunit      = models.CharField(max_length=255)
    size          = models.IntegerField(default=1)
    batch         = models.ForeignKey(Batch, null=True)

    def __getattribute__(self, key):
        if key == 'task_id':
            return self.task_instance.id
        elif key == 'on_main_worker':
            return self.task_instance.worker == self.worker
        return super(WorkUnit, self).__getattribute__(key)

    def json_safe(self):
        return {
            'subtask_key':self.subtask_key,
            'workunit_key':self.workunit,
            'args':self.args,
            'started':self.started.strftime('%Y-%m-%d %H:%m:%S') \
                                                    if self.started else None,
            'completed':self.completed.strftime('%Y-%m-%d %H:%m:%S') \
                                                if self.completed else None,
            'worker':self.worker,
            'status':self.status,
            'log_retrieved':self.log_retrieved
        }

    def transmitable(self):
        return {self.subtask_key:[self.workunit]}


class Batch(AbstractJob):
    """
    Batch contains a set of WorkUnits.  Batches are a proxy to most properties
    and methods possessed by WorkUnits.  Executing methods or setting variables
    on a Batch sets them on all contained WorkUnits.  This allows a Batch to be
    used transparently almost anywhere a WorkUnit can be.
    """
    task_instance = models.ForeignKey(TaskInstance, related_name='batches')
    size          = models.IntegerField(default=1)
    
    def __init__(self, iterator=None):
        if iterator:
            workunits = {}
            batch = {}
            for workunit in iterator:
                workunits[workunit.workunit] = workunit
                try:
                    batch[workunit.subtask_key].append(workunit.workunit)
                except KeyError:
                    batch[workunit.subtask_key] = [workunit.workunit]
            self.workunits = workunits
            self._transmitable = batch
        else:
            self.workunits = []
            self._transmitable = {}
    
    def __getattribute__(self, key):
        if key == 'task_id':
            return self.task_instance.id
        elif key == 'task_key':
            return self.task_instance.task_key
        elif key == 'on_main_worker':
            return self.task_instance.worker == self.worker
        return super(Batch, self).__getattribute__(key)
    
    def __getitem__(self, key):
        return self.workunits[key]
    
    def __setattr__(self, key, value):
        """
        Overridden to save values in contained WorkUnits as well.
        """
        super(Batch, self).__setattr__(key, value)
        if key in ('worker', 'started', 'completed'):
            for workunit in self.workunits.values():
                workunit.__dict__[key] = value
    
    def __str__(self):
        return 'Batch: %s @ %s' % (self.workunits.keys(), self.worker)
    
    def add(self, workunit):
        """
        Adds a workunit to this batch
        """
        self.workunits.append(workunit)
        try:
            self._transmitable[workunit.subtask_key].append(workunit.workunit)
        except KeyError:
            self._transmitable[workunit.subtask_key] = [workunit.workunit]
    
    def save(self):
        """
        Saves all workunits contained in this batch
        """
        for workunit in self.workunits.values():
            workunit.save()
    
    def transmitable(self):
        return self._transmitable