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
        ]

        self._listeners = {'MANAGER_INIT':self.update_all,
                           'TASK_FINISHED':self.update}


    def task_statistics(self, task_key):
        """
        Returns task stats given the task key.  These are broken down by 
        worker and version 
        """
        if task_key:
            stats_query = Statistics.objects.filter(task_key=task_key)
            if stats_query:
                return stats_query[0].get_data()
        else:
            return {}


    def update_all(self):
        """
        Updates all unaccounted for completed TaskInstance's.
        """
        task_instances = TaskInstance.objects.filter(statistics_calculated=False).exclude(completed=None)
        for task_instance in task_instances:
            self.update(task_instance)


    def update(self, task_instance):
        """
        Updates statistics of the associated task key,
        subtasks, and workers.
        """
        task_key = task_instance.task_key

        # retrieve stats dictionary
        stats_query = Statistics.objects.filter(task_key=task_key)
        if stats_query:
            stats_obj = stats_query[0]
            stats = stats_query[0].get_data()

        else:
            stats_obj = Statistics(task_key=task_key)
            stats = {'task': self.init_stat_dict(), 'subtask': {}}
            stats['task']['workers'] = {}
            stats['task']['versions'] = {}


        time_delta = (task_instance.completed - task_instance.started).seconds
        self.tick_stats(time_delta, stats['task'])
        self.subtask_stats(task_instance, stats['subtask'])
        self.breakdown_stats(task_instance.worker, stats['task']['workers'], time_delta)
        self.breakdown_stats(task_instance.version, stats['task']['versions'], time_delta)

        task_instance.statistics_calculated = True
        task_instance.save()
        stats_obj.save_data(stats)


    def subtask_stats(self, task_instance, stats):
        """
        Given a TaskInstance, calculate subtask stats. 
        """
        workunits = task_instance.workunits.values()
        if workunits:
            for work in workunits:
                time_delta = (work['completed'] - work['started']).seconds
                key = work['subtask_key']

                # have we seen this subtask before?
                if not key in stats:
                    stats[key] = self.init_stat_dict()

                self.tick_stats(time_delta, stats[key])

                # have we seen this worker before?
                if not 'workers' in stats[key]:
                    stats[key]['workers'] = {}
                self.breakdown_stats(work.worker, stats[key]['workers'], time_delta)


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
