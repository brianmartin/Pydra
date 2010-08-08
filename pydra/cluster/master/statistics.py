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
from pydra.models import TaskInstance, WorkUnit
import pydra_settings

# init logging
import logging
logger = logging.getLogger('root')

class StatisticsModule(Module):

    def __init__(self):
        self._interfaces = [
            self.get_task_stats,
            self.get_all_task_stats,
            self.get_subtask_stats,
            self.get_all_subtask_stats,
            self.get_json_safe,
        ]

        self._task_stat_data = {}
        self._task_stat_indices = {}
        self._subtask_stat_data = {}
        self._total_time = 0.0 #in seconds

    def _register(self, manager):
        Module._register(self, manager)
        reactor.callLater(2, self.calc_all_tasks)


    # convenience accessor functions
    # {
    def get_task_stats(self, task_key):
        return self._task_stat_data[task_key] if task_key in self._task_stat_data else {}

    def get_all_task_stats(self):
        return self._task_stat_data

    def get_subtask_stats(self, subtask_key):
        return self._subtask_stat_data[subtask_key] if subtask_key in self._subtask_stat_data else {}

    def get_all_subtask_stats(self):
        return self._subtask_stat_data

    def get_json_safe(self):
        return [{'id':k, 'percentage': (v['num_completed'] * v['avg']) / self._total_time}\
                    for k,v in self._task_stat_data.items()]
    # }

    def calc_all_tasks(self):
        """
        Checks that stat calculations have been initiated for all unique task_key's.
        """
        for task_key in set(TaskInstance.objects.values_list('task_key')):

            # if this is a new task then start calculating stats
            if not self.get_task_stats(task_key[0]):
                self.task_stats(task_key[0])

            # print task stats
            logger.info("%s stats: %s" % (task_key[0], self.get_task_stats(task_key[0])))

        for subtask_key, subtask_stats in self._subtask_stat_data.items():
            # print subtask stats
            logger.info("%s subtask stats: %s" % (subtask_key, subtask_stats))

        # call later to recheck for new tasks
        reactor.callLater(10, self.calc_all_tasks)


    def task_stats(self, task_key, delay=3, max_delay=60, backoff=2):
        """
        Runs _task_stats repeatedly with delayed rerun
        (time until next rerun increases by a factor of 'backoff')
        """
        # if new info was added, reset delay:
        if self._task_stats(task_key):
            delay = 3

        else:
            delay = min(max_delay, delay * backoff)

        reactor.callLater(delay, self.task_stats, task_key, delay=delay)


    def _task_stats(self, task_key):
        """
        Looks for new TaskInstance's associated with task_key.
        If found, it updates statistics using tick_stats.
        """
        # if it's a new task initialize the index and data
        if not task_key in self._task_stat_indices:
            self._task_stat_indices[task_key] = 0
            self._task_stat_data[task_key] = self.init_stat_dict()

        index = self._task_stat_indices[task_key] 
        stats = self._task_stat_data[task_key]
        stats.setdefault('workunits', self.init_stat_dict())

        # get the task_instances that have completed since statistics were last calculated
        task_instances = TaskInstance.objects.filter(task_key=task_key).exclude(completed=None)[index:]

        #if new instances of the task exist
        if task_instances:
            # keep track of where we left off
            index += task_instances.count()
            for task_instance in task_instances:
                time_delta = (task_instance.completed - task_instance.started).seconds
                self.tick_stats(time_delta, stats)
                self.workunit_stats(task_instance, stats['workunits'])
                self._total_time += time_delta
            stats['std_dev'] = sqrt(stats['variance']) if stats['variance'] != -1 else -1

            return True

        # otherwise no new info
        else:
            return False


    def workunit_stats(self, task_instance, stats):
        """
        Calculates statistics of workunits given a TaskInstance.
        """
        workunits = task_instance.workunits.values()
        for work in workunits:
           time_delta = (work['completed'] - work['started']).seconds
           self.tick_stats(time_delta, stats)
           # while we're looping through unique workunits and have already
           # retrieved time_delta, calculate subtask stats
           self.subtask_stats(work, time_delta)


    def subtask_stats(self, work, time_delta):
        """
        Given a WorkUnit, tick subtask stats of the related subtask_key
        """
        stats = self._subtask_stat_data[work['subtask_key']] if work['subtask_key'] in self._subtask_stat_data\
                                                            else self.init_stat_dict()
        self.tick_stats(time_delta, stats)


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

    def init_stat_dict(self):
        return {'num_completed': 0, 'avg': 0, 'M2': 0.0, 'min': -1, 'max': -1, \
                    'variance': -1, 'std_dev': 0.0, 'sum_time': 0}
