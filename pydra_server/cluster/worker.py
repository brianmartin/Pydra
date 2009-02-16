#! /usr/bin/python

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

#
# Setup django environment 
#
if __name__ == '__main__':
    import sys
    import os

    #python magic to add the current directory to the pythonpath
    sys.path.append(os.getcwd())

    #
    if not os.environ.has_key('DJANGO_SETTINGS_MODULE'):
        os.environ['DJANGO_SETTINGS_MODULE'] = 'settings'

import os, sys
from twisted.spread import pb
from twisted.internet import reactor
from twisted.cred import credentials
from twisted.internet.protocol import ReconnectingClientFactory
from threading import Lock

from task_manager import TaskManager
from constants import *

"""
   Subclassing of PBClientFactory to add automatic reconnection
"""
class MasterClientFactory(pb.PBClientFactory):

    def __init__(self, reconnect_func, *args, **kwargs):
        pb.PBClientFactory.__init__(self)
        self.reconnect_func = reconnect_func
        self.args = args
        self.kwargs = kwargs

    def clientConnectionLost(self, connector, reason):
        print '[warning] Lost connection to master.  Reason:', reason
        pb.PBClientFactory.clientConnectionLost(self, connector, reason)
        self.reconnect_func(*(self.args), **(self.kwargs))

    def clientConnectionFailed(self, connector, reason):
        print '[warning] Connection to master failed. Reason:', reason
        pb.PBClientFactory.clientConnectionFailed(self, connector, reason)



"""
Worker - The Worker is the workhorse of the cluster.  It sits and waits for Tasks and SubTasks to be executed
         Each Task will be run on a single Worker.  If the Task or any of its subtasks are a ParallelTask 
         the first worker will make requests for work to be distributed to other Nodes
"""
class Worker(pb.Referenceable):

    def __init__(self, master_host, master_port, node_key, worker_key):
        self.id = id
        self.__task = None
        self.__results = None
        self.__lock = Lock()
        self.master = None
        self.master_host = master_host
        self.master_port = master_port
        self.node_key = node_key
        self.worker_key = worker_key
        self.reconnect_count = 0

        #load tasks that are cached locally
        self.task_manager = TaskManager()
        self.task_manager.autodiscover()
        self.available_tasks = self.task_manager.registry

        print '[info] Started Worker: %s' % worker_key
        self.connect()

    """
    Make initial connections to all Nodes
    """
    def connect(self):
        print '[info] worker:%s - connecting to master @ %s:%s' % (self.worker_key, self.master_host, self.master_port)
        factory = MasterClientFactory(self.reconnect)
        reactor.connectTCP(self.master_host, self.master_port, factory)
        deferred = factory.login(credentials.UsernamePassword(self.worker_key, "1234"), client=self)
        deferred.addCallbacks(self.connected, self.reconnect, errbackArgs=("Failed to Connect"))

    def reconnect(self, *arg, **kw):
        self.master = None
        reconnect_delay = 5*pow(2, self.reconnect_count)
        #let increment grow exponentially to 5 minutes
        if self.reconnect_count < 6:
            self.reconnect_count += 1 
        print '[debug] worker:%s - reconnecting in %i seconds' % (self.worker_key, reconnect_delay)
        self.reconnect_call_ID = reactor.callLater(reconnect_delay, self.connect)

    """
    Callback called when connection to master is made
    """
    def connected(self, result):
        self.master = result
        self.reconnect_count = 0
        print '[info] worker:%s - connected to master @ %s:%s' % (self.worker_key, self.master_host, self.master_port)

    """
    Callback called when conenction to master fails
    """
    def connect_failed(self, result):
        self.reconnect()

    """
     Runs a task on this worker
    """
    def run_task(self, key, args={}, subtask_key=None, workunit_key=None, available_workers=1):
        #Check to ensure this worker is not already busy.
        # The Master should catch this but lets be defensive.
        with self.__lock:
            if self.__task:
                return "FAILURE THIS WORKER IS ALREADY RUNNING A TASK"
            self.__task = key
            self.__subtask = subtask_key
            self.__workunit_key = workunit_key

        self.available_workers = available_workers

        print '[info] Worker:%s - starting task: %s:%s' % (self.worker_key, key,subtask_key)

        #create an instance of the requested task
        self.__task_instance = object.__new__(self.available_tasks[key])
        self.__task_instance.__init__()
        self.__task_instance.parent = self

        return self.__task_instance.start(args, subtask_key, self.work_complete)


    """
    Return the status of the current task if running, else None
    """
    def status(self):
        # if there is a task it must still be running
        if self.__task:
            return (WORKER_STATUS_WORKING, self.__task, self.__subtask)

        # if there are results it was waiting for the master to retrieve them
        if self.__results:
            return (WORKER_STATUS_FINISHED, self.__task, self.__subtask)

        return (WORKER_STATUS_IDLE,)


    """
    Callback that is called when a job is run in non_blocking mode.
    """
    def work_complete(self, results):
        self.__task = None

        # if the master is still there send the results
        if self.master:
            deferred = self.master.callRemote("send_results", results, self.__workunit_key)
            deferred.addErrback(self.send_results_failed, results, self.__workunit_key)

        # master disapeared, hold results until it requests them
        else:
            self.__results = results

    """
    Errback called when sending results to the master fails.  Worker
    should hold onto results until the master requests it.

    TODO examine auto-resend.  its possible the first re-send could fail
    if it fails for a reason other than the master is offline then results
    will never be retrieved
    """
    def send_results_failed(self, results, task_results, workunit_key):
        self.__results = task_results
        self.__workunit_key = workunit_key


    """
    Function called to make the subtask receive the results processed by another worker
    """
    def receive_results(self, results, subtask_key, workunit_key):
        subtask = self.__task_instance.get_subtask(subtask_key.split('.'))
        subtask.parent._work_unit_complete(results, workunit_key)

    """
    Requests a work unit be handled by another worker in the cluster
    """
    def request_worker(self, subtask_key, args, workunit_key):
        print '[info] Worker:%s - requesting worker for: %s' % (self.worker_key, subtask_key)
        deferred = self.master.callRemote('request_worker', subtask_key, args, workunit_key)

    """
    Recursive function so tasks can find this worker
    """
    def get_worker(self):
        return self

    # returns the status of this node
    def remote_status(self):
        return self.status()

    # returns the list of available tasks
    def remote_task_list(self):
        return self.available_tasks.keys()

    # run a task
    def remote_run_task(self, key, args={}, subtask_key=None, workunit_key=None, available_workers=1):
        return self.run_task(key, args, subtask_key, workunit_key, available_workers)

    # allows the master to request results
    def remote_receive_results(self, results, subtask_key, workunit_key):
        return self.receive_results(results, subtask_key, workunit_key)

if __name__ == "__main__":
    master_host = sys.argv[1]
    master_port = int(sys.argv[2])
    node_key    = sys.argv[3]
    worker_key  = sys.argv[4]

    '''realm = ClusterRealm()
    realm.server = Worker('%s:%s' % (host,port))
    checker = checkers.InMemoryUsernamePasswordDatabaseDontUse()
    checker.addUser("tester", "456")
    p = portal.Portal(realm, [checker])

    reactor.listenTCP(port, pb.PBServerFactory(p))
    '''
    worker = Worker(master_host, master_port, node_key, worker_key)
    reactor.run()
