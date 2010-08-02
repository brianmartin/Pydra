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

        try: 
            self.indices[task_key]
        except KeyError:
            self.indices[task_key] = 0

        tasks = TaskInstance.objects.filter(task_key=task_key).exclude(completed=None)[self.indices[task_key]:]
        #if the task has been run since the last update, do:
        if tasks:
            self.indices[task_key] += tasks.count()
            for task in tasks: 
                workunits = WorkUnit.objects.filter(task_instance=task)
                try:
                    self.sums[task_key]
                except KeyError:
                    self.sums[task_key] = {'num_completed': 0, 'avg': 0, 'M2': 0, 'min': -1, 'max': -1, \
                                           'variance': -1, 'std_dev': 0, 'workunits': ''}

                self.sums[task_key]['workunits'] = workunits

                time_delta = (task.completed - task.started).seconds

                # max
                self.sums[task_key]['max'] = max(time_delta, self.sums[task_key]['max'])

                # min
                self.sums[task_key]['min'] = time_delta if self.sums[task_key]['min'] == -1 \
                                                        else min(time_delta, self.sums[task_key]['min'])

                # number completed
                self.sums[task_key]['num_completed'] += 1

                # running average using deviation from average (also used for online variance calculation)
                delta = time_delta - self.sums[task_key]['avg']
                self.sums[task_key]['avg'] = self.sums[task_key]['avg'] + delta / self.sums[task_key]['num_completed']

                # online variance
                self.sums[task_key]['M2'] = self.sums[task_key]['M2'] + delta * (time_delta - self.sums[task_key]['avg'])
                if self.sums[task_key]['num_completed'] - 1:
                    self.sums[task_key]['variance'] = self.sums[task_key]['M2'] / (self.sums[task_key]['num_completed'] - 1)

            # standard deviation from variance
            self.sums[task_key]['std_dev'] = sqrt(self.sums[task_key]['variance'])

            return self.sums[task_key]

        else:
            try:
                # if previously calculated stats exist return them
                return self.sums[task_key]
            except KeyError:
                logger.info("%s has not yet been run or is not yet completed." % task_key)
                return {}
