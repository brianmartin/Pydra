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
from threading import Thread

class CloudProvisioningModule(Module):

    _signals = [
        'NODE_CREATED',
        'NODE_DELETED',
        'NODE_EDITED'
    ]

#    _shared = []

    def __init__(self):
        self._interfaces = [
            self.list_nodes,
            self.request_node
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

        def add_booted_nodes():
            for node_libcloud in self.conn.list_nodes():
                #if already added or still booting: don't add
                if CloudNode.objects.get(name=node.name) or node.public_ip==['']:
                    pass
                else:
                    self.create_node(node_libcloud)

        def get_info():
            Thread(target=create_security_group()).start()
            Thread(target=get_images()).start()
            Thread(target=get_sizes()).start()

        connect_ec2()
        get_info()
#        self.request_node()
#        add_booted_nodes()

    def request_node(self):
        Thread(target=self._request_node).start()

    def _request_node(self):
        logger.info("Creating EC2 node.")
        node_libcloud = self.conn.create_node(name='Pydra', image=self.image, size=self.size, ex_securitygroup="Pydra")
        logger.info("Node created, name: " + node_libcloud.name)
        logger.info("Waiting for hostname.")
        while node_libcloud.public_ip==['']:
            time.sleep(15)
            node_libcloud = [node for node in self.conn.list_nodes() if node.name==node_libcloud.name][0]
        logger.info("Got hostname..")
        
        create_node(node_libcloud)

    def create_node(self, node_libcloud):
        logger.info("Adding cloud node..")
        node = CloudNode.objects.create(host=node_libcloud.public_ip[0], port=pydra_settings.PORT, ex_securitygroup="Pydra")
        self.emit('NODE_CREATED', node)

    def list_nodes(self):
        """
        Lists nodes available on EC2 (not necessarily added as pydra nodes)
        """
        #return list of id's not node objects
        return [node.public_ip for node in self.conn.list_nodes() if node.name=='Pydra']

    
