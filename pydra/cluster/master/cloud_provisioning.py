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
        'NODE_EDITED',
        'NODE_UPDATED'
    ]

    _shared = []

    def __init__(self):
        self._interfaces = [
            self.list_cloudnodes,
            self.cloudnode_delete,
            self.cloudnode_edit
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
            try:
                node_images = self.conn.list_images()
                self.image = [image for image in node_images if image.id=="ami-b17c95d8"][0]
                logger.info("Got image list, and found Pydra AMI.")
            except:
                logger.warning("Image list not recieved or Pydra AMI not found.")

        def get_sizes():
            self.sizes = self.conn.list_sizes()

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


    def cloudnode_request(self, node_pydra):
        """
        Thread wrapper for _request_cloudnode
        """
        logger.info("hello from cloudnode_request!")
        # hardcoded -- you're so BAAAD!
        self.size = self.sizes[2]
        # Change this!

        logger.info(self.size)
        Thread(target=self._cloudnode_request, args=(node_pydra,)).start()

    def _cloudnode_request(self, node_pydra):
        """
        Request a cloud instance be booted.  The instance is automatically added as a pydra node after the hostname is received.
        """
        logger.info("Creating EC2 node.")
        #wait for image and size options to be retrieved
        if not self.image or not self.size:
            time.sleep(5)
            logger.info("Waiting on size or image.")
        node_libcloud = self.conn.create_node(name='Pydra', image=self.image, size=self.size, ex_securitygroup="Pydra")
        logger.info("Node created, name: " + node_libcloud.name)
        logger.info("Waiting for hostname.")
        while node_libcloud.public_ip==['']:
            time.sleep(15)
            node_libcloud = [node for node in self.conn.list_nodes() if node.name==node_libcloud.name][0]
        logger.info("Got hostname..")
        
        self.cloudnode_create(node_libcloud, node_pydra)

    def cloudnode_create(self, node_libcloud, node_pydra):
        """
        Update booted cloud instance's information.
        """
        logger.info("Updating cloud node..")
        update_values = {'id':node_pydra.id, 'host':node_libcloud.public_ip[0], 'security_group':"Pydra"}
        self.cloudnode_edit(self, update_values)
        

    def cloudnode_delete(self, id):
        """
        deletes a cloudnode with the id passed in.
        """
        Thread(target=self._cloudnode_delete).start()
        node = CloudNode.objects.get(id=id)
        node.deleted = True
        node.save()
        self.emit('NODE_DELETED', node)

    def _cloudnode_delete(self, node_pydra):
        """
        destroys the cloud instance of the node passed in.
        """
        try:
            node_libcloud = [node for node in self.conn.list_nodes() if node.name==node_pydra.name][0]
            self.conn.destroy_node(node_libcloud)
            logger.info("CloudNode instance " + node_libcloud.name + " terminated.")
        except:
            logger.warning("CloudNode instance could not be terminated.  Instance must be terminated manually.")


    def cloudnode_edit(self, values):
        """
        Updates or Creates a cloudnode with the values passed in.  If an id field
        is present it will be update the existing cloudnode.  Otherwise it will
        create a new cloudnode
        """
        logger.info("hello from cloudnode_edit!!")
        logger.info(values)
        if values.has_key('id'):
            node = CloudNode.objects.get(pk=values['id'])
            updated = values['port'] == node.port
            new = False
        else:
            node = CloudNode()
            new = True

        for k,v in values.items():
            node.__dict__[k] = v
        node.save()


        logger.info("hello before request, true?: " + str(new))
        if new:
            node.host = "booting"
            node.save()
            self.cloudnode_request(node)
        else:            
            self.emit('NODE_UPDATED', node)

        
    def list_cloudnodes(self):
        """
        Lists nodes available on EC2 (not necessarily added as pydra nodes)
        """
        #return list of id's not node objects
        return [node.public_ip for node in self.conn.list_nodes() if node.name=='Pydra']
