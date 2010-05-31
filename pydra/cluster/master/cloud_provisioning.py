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
from pydra.models import CloudNode
import pydra_settings

import logging
logger = logging.getLogger('root')

import time

class CloudProvisioningModule(Module):

    _signals = [
        'NODE_CREATED',
        'NODE_DELETED',
        'NODE_EDITED'
    ]

    _shared = []

    def __init__(self):
        self._interfaces = [
            self.list_nodes
        ]
        self._listeners = {'MANAGER_INIT':self.cloud}

    def _register(self, manager):
        Module._register(self, manager)
        self.images = list()

    def cloud(self, callback=None):
        
        def connect_ec2():
            Driver = get_driver(Provider.EC2)
            self.conn = Driver(pydra_settings.EC2_ACCESS_ID, pydra_settings.EC2_SECRET_KEY)

        def get_images():
            logger.info("Retrieving image list")
            node_images = self.conn.list_images()
            self.image = [image for image in node_images if image.id=="ami-b17c95d8"][0]
            logger.info("Got image list, and found Pydra AMI.")

        def get_sizes():
            self.sizes = self.conn.list_sizes()
            self.size = self.sizes[2]

        def create_security_group():
            try:
                self.conn.ex_create_security_group("Pydra", "Programatic creation of permissive security group")
                self.conn.ex_authorize_security_group_permissive("Pydra")
                logger.info("Amazon EC2 security group created.")
            except:
                logger.info("Amazon EC2 security group already created.")

        def create_node():
            logger.info("Creating EC2 node.")
            node_libcloud = self.conn.create_node(name='Pydra', image=self.image, size=self.size, ex_securitygroup("Pydra"))
            logger.info("Node created, name: " + node_libcloud.name)
            while [node for node in self.conn.list_nodes() if node.name==node_libcloud.name][0].public_ip==['']:
                time.sleep(15)
                logger.info("Waiting for hostname.")
            logger.info("Got hostname..")
            logger.info("Adding cloud node..")
            #bug here - change array index 
            node = Node.objects.create(host=self.conn.list_nodes()[0].public_ip[0], port=pydra_settings.PORT)
            self.emit('NODE_CREATED', node)

        def add_booted_nodes():
            for node in self.conn.list_nodes():
                if node.public_ip==['']:
                    pass
                else:
                    cloudnode = CloudNode.objects.create(host=node.public_ip[0], port=pydra_settings.PORT, service_provider='EC2')
                    self.emit('NODE_CREATED', cloudnode)

        connect_ec2()
#        create_security_group()
#        get_images()
#        get_sizes()
#        create_node()
        add_booted_nodes()

    def list_nodes(self):
        """
        Lists nodes available on EC2
        """
        #return list of id's not node objects
        return [node.public_ip for node in self.conn.list_nodes() if node.name=='Pydra']
