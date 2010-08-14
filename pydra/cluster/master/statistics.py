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
from twisted.internet import reactor

from datetime import datetime
from math import sqrt

from pydra.cluster.module import Module
from pydra.models import TaskInstance, WorkUnit, Statistics
import pydra_settings

# init logging
import logging
logger = logging.getLogger('root')

class StatisticsModule(Module):

    def __init__(self):
        self._interfaces = [
            self.task_statistics,
            self.subtask_statistics,
        ]

        self._listeners = {'MANAGER_INIT':self.initialize,
                           'TASK_FINISHED':self.update}


    def initialize(self):
        self.retrieve_data()
        self.update_all()

    def retrieve_data(self):
        if not Statistics.objects.all():
            self._db_obj = Statistics()
        else:
            self._db_obj = Statistics.objects.all()[0]
        self._db = self._db_obj.get_data()


    def task_statistics(self, task_key=None, subtask_key=None, worker=None, version=None):
        """
        Returns task stats given the task key.  These may be broken down by either
        worker or version (where worker takes precedence)
        """
        if not task_key and not subtask_key:
            return self._db['task']
        elif task_key in self._db['task']:
            stats = self._db['task'][task_key]
        elif subtask_key in self._db['subtask']:
            stats = self._db['subtask'][subtask_key]
        else:
            return {}

        if worker and worker in stats['workers']:
            return stats['workers'][worker]
        elif version and version in stats['versions']:
            return stats['versions'][version]
        else:
            return stats


    def update_all(self):
        """
        Updates all unaccounted for completed TaskInstance's.
        """
        task_instances = TaskInstance.objects.exclude(completed=None)[self._db['index']:]
        for task_instance in task_instances:
            self.update(task_instance)


    def update(self, task_instance):
        """
        Looks for new TaskInstance's.
        If found, it updates statistics of the associated task key,
        subtasks, and workers.
        """
        task_key = task_instance.task_key

        # if it's a new task initialize the index and data
        if not task_key in self._db['task']:
            self._db['task'][task_key] = self.init_stat_dict()
            self._db['task'][task_key]['workers'] = {}
            self._db['task'][task_key]['versions'] = {}

        stats = self._db['task'][task_key]

        time_delta = (task_instance.completed - task_instance.started).seconds
        self.tick_stats(time_delta, stats)
        self.subtask_stats(task_instance)
        self.breakdown_stats(task_instance.worker, stats['workers'], time_delta)
        self.breakdown_stats(task_instance.version, stats['versions'], time_delta)

        # keep track of where we left off
        self._db['index'] += 1

        self._db_obj.save_data(self._db)


    def subtask_stats(self, task_instance):
        """
        Given a TaskInstance, calculate subtask stats. 
        """
        workunits = task_instance.workunits.values()
        if workunits:
            for work in workunits:
                time_delta = (work['completed'] - work['started']).seconds

                # have we seen this subtask before?
                if not work['subtask_key'] in self._db['subtask']:
                    self._db['subtask'][work['subtask_key']] = self.init_stat_dict()
                stats = self._db['subtask'][work['subtask_key']]

                self.tick_stats(time_delta, stats)

                # have we seen this worker before?
                if not 'workers' in stats:
                    stats['workers'] = {}
                self.worker_stats(work['worker'], stats['workers'], time_delta)


    def breakdown_stats(self, key, stats, time_delta):
        """
        Given a TaskInstance, calculate stats by key.
        """
        if not key in stats:
            stats[key] = self.init_stat_dict()
        self.tick_stats(time_delta, stats[key])


    def tick_stats(self, x, stats):
        """
        Adds one input, x, to the dictionary of stats given.
        """
        # sum of x's
        stats['sum_time'] += x
        # max
        stats['max'] = max(x, stats['max'])
        # min
        stats['min'] = x if stats['min'] == -1 else min(x, stats['min'])
        # number completed
        stats['num_completed'] += 1
        # running average using deviation from average (also used for online variance calculation)
        delta = x - stats['avg']
        stats['avg'] = stats['avg'] + delta / stats['num_completed']
        # online variance
        stats['M2'] = stats['M2'] + delta * (x - stats['avg'])
        if stats['num_completed'] - 1:
            stats['variance'] = stats['M2'] / (stats['num_completed'] - 1)
        # standard deviation
        stats['std_dev'] = sqrt(stats['variance']) if stats['variance'] != -1 else -1

    def init_stat_dict(self):
        """
        Base statistics measures
        """
        return {'num_completed': 0, 'avg': 0, 'M2': 0.0, 'min': -1, 'max': -1, \
                    'variance': -1, 'std_dev': 0.0, 'sum_time': 0}
