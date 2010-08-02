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
            self.calc,
            self.task_stats,
        ]

        self.sums = {}
        self.indices = {}

    def _register(self, manager):
        Module._register(self, manager)
        reactor.callLater(2, self.calc)

    def calc(self):
        """
        Recalculates stats for all unique tasks that have been run.
        """
        for task_key in set(TaskInstance.objects.values_list('task_key')): 
            results = self.task_stats(task_key[0])
            logger.info("%s stats: %s" % (task_key[0], results))
        reactor.callLater(2, self.calc) 

    def task_stats(self, task_key):
        """
        Returns task statistics given the task key.
        """

        # if it's a new task initialize the index
        try: 
            self.indices[task_key]
        except KeyError:
            self.indices[task_key] = 0

        # get task stats data (or initialize)
        try:
            stats = self.sums[task_key]
        except KeyError:
            stats = self.sums[task_key] = {'num_completed': 0, 'avg': 0, 'M2': 0, 'min': -1, 'max': -1, \
                                           'variance': -1, 'std_dev': 0, 'workunits': ''}

        # get the task_instances that have completed since statistics were last calculated
        task_instances = TaskInstance.objects.filter(task_key=task_key).exclude(completed=None)[self.indices[task_key]:]

        #if the task has been run since the last update, do:
        if task_instances:
            # keep track of where we left off
            self.indices[task_key] += task_instances.count()
            for task_instance in task_instances:
                self.tick_stats((task_instance.completed - task_instance.started).seconds, stats)
            stats['std_dev'] = sqrt(stats['variance'])

            return stats

        # otherwise, no new info
        else:
            if not stats:
                logger.info("%s has not yet been run or is not yet completed." % task_key)
            return stats

    def tick_stats(self, x, stats):
        """
        Adds one input, x, to the dictionary of stats given.
        """
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


    def workunit_stats(self, task_key):
        """
        Returns statistics by workunit given the task key.
        """

        assoc_task = TaskInstance.objects.filter(task_key=task_key)
        workunits = WorkUnit.objects.filter(task_instance=assoc_task)
