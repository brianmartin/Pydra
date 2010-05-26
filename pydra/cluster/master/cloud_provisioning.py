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
from libcloud.types import Provider
from libcloud.providers import get_driver

from pydra.cluster.module import Module
from pydra.models import Node
import pydra_settings

import logging
logger = logging.getLogger('root')

class CloudProvisioningModule(Module):

    _signals = [
        'NODE_CREATED',
        'NODE_DELETED',
        'NODE_EDITED'
    ]

    _shared = [
        'images'
    ]

    def __init__(self):
        self._interfaces = [
            self.list_images
        ]
        self.listeners = {'MANAGER_INIT':self.get_images}

    def _register(self, manager):
        Module._register(self, manager)
        self.images = list()

    def get_images(self, callback=None):
        Driver = get_driver(Provider.EC2)
        conn = Driver(pydra_settings.EC2_ACCESS_ID, pydra_settings.EC2_SECRET_KEY)
        return conn.list_images()

    def list_images(self, page=1):
        """
        Lists images available on EC2
        """
        #cast to list 
        return list(self.images)
