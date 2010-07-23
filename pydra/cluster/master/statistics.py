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
from pydra.cluster.master.scheduler import TaskScheduler
import pydra_settings

from pydra.models import TaskInstance

# init logging
import logging
logger = logging.getLogger('root')

class StatisticsModule(Module):

    def __init__(self):
	self._friends = {
	    'scheduler' : TaskScheduler,
	}

	self._interfaces = [
	    self.stats,
	]

    def _register(self, manager):
        Module._register(self, manager)
	reactor.callLater(2, self.stats)

    def stats(self, callback=None):
	tasks = TaskInstance.objects.all()
	sums = {}
	for task in tasks: 
	    try:
		sums[task.task_key]
	    except KeyError:
		sums[task.task_key] = {'num_completed': 0, 'summed_time': 0, \
				       'summed_squared_time': 0}
	    if task.completed:
		time_delta = (task.completed - task.started).seconds
		sums[task.task_key]['summed_time'] += time_delta
		sums[task.task_key]['summed_squared_time'] += time_delta**2
		sums[task.task_key]['num_completed'] += 1

	# TODO: optimize by switching to a running variance/stddev calculation
	for task, values in sums.items():
	    sums[task]['std_dev'] = sqrt((sums[task]['summed_squared_time'] - (sums[task]['summed_time']**2 \
					/ sums[task]['num_completed'])) / (sums[task]['num_completed'] - 1))	

	logger.info("task stats: %s" % str(sums))
	self.recall()

    def recall(self):
	reactor.callLater(2, self.stats)
