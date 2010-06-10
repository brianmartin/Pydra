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

from time import sleep
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

    def cloud(self, callback=None):
        """
        Initialize and connect to services for which credentials are provided in pydra_settings.
        """
        
        #define credential names (secure, host, and port may also be keys here):
        self.crednames = {'EC2': {'id': 'EC2_ACCESS_ID', 'secret': 'EC2_SECRET_KEY'},
                      'RACKSPACE': {'id': 'RACKSPACE_USER', 'secret': 'RACKSPACE_API'},
                      'EUCALYPTUS': {'id': 'EUCALYPTUS_ACCESS_ID', 'key':'EUCALYPTUS_SECRET_KEY', 'host': 'EUCALYPTUS_HOST'},
                      'SLICEHOST': {'id': 'SLICEHOST_USER', 'key': 'SLICEHOST_SECRET_KEY'},
                      'LINODE': {'id': 'LINODE_USER', 'key': 'LINODE_SECRET_KEY'},
                      }
        self.creds = {}
        self.conn = {}
        self.image = {}
        self.sizes = {}
        
        def connect_all():
            """
            Connect to all services for which credentials are defined.
            """
            verify_creds()
            for service in self.creds.keys():
                Thread(target=connect(service)).start()

        def verify_creds():
            """
            Read in all credentials that are defined in pydra_settings and are not empty.
            """
            for service in self.crednames.keys():
                if all(map(lambda x: hasattr(pydra_settings, x) and eval('pydra_settings.' + x) != '', self.crednames[service].values())):
                        self.creds[service] = [eval('pydra_settings.' + self.crednames[service]['id']), \
                                                 dict([(k, eval('pydra_settings.' + v)) for k,v in self.crednames[service].iteritems() if k != 'id'])]

        def connect(service):
            """
            Connect to service and gather available instance images and sizes (if credentials are defined).
            """
            #attempt connection
            try:
                Driver = get_driver(eval('Provider.' + service))
                self.conn[service] = Driver(self.creds[service][0], **self.creds[service][1])
            except:
                logger.error("Unable to connect to " + service + ". (Perhaps wrong credentials?)")
                return

            #gather info
            add_booted_nodes(service)
            get_images(service)
            get_sizes(service)
                
        def get_images(service):
            """
            Store image list from specified service.
            """
            logger.info("Retrieving " + service + " image list...")
            try:
                self.image[service] = filter(lambda x: x.id == eval('pydra_settings.' + service + '_IMAGE_ID'), self.conn[service].list_images())[0]
                logger.info("Got " + service + " image list, and found Pydra image.")
            except Exception, e:
                logger.warning(service + " image list not received or Pydra image not found.")

        def get_sizes(service):
            """
            Store list of instance sizes available from specified service.
            """
            self.sizes[service] = self.conn[service].list_sizes()

        def create_security_group():
            """
            Check for the Pydra EC2 security group.
            This policy is entirely permissive as this is the only way to specify using libcloud.
            """
            try:
                self.conn.ex_create_security_group("Pydra", "Permissive security group for Pydra cloud provisioning.")
                self.conn.ex_authorize_security_group_permissive("Pydra")
                logger.info("Amazon EC2 security group created.")
            except:
                logger.info("Amazon EC2 security group already created.")

        def add_booted_nodes(service):
            """
            Add available instances that have already been booted to the Pydra db.
            This is useful if the Master is restarted.
            """
            for node_libcloud in self.conn[service].list_nodes():
                #if already added or still booting: don't add
                if CloudNode.objects.get(name=node.name) or node.public_ip==['']:
                    pass
                else:
                    self.create_node(node_libcloud)

        connect_all()

    def cloudnode_request(self, node_pydra):
        """
        Thread wrapper for _request_cloudnode
        """
        # only works for EC2
        # add field to cloudnode model
        self.size = self.sizes[str(node_pydra.service_provider)][2]
        # Change this!

        logger.info(self.size)
        Thread(target=self._cloudnode_request, args=(node_pydra,)).start()

    def _cloudnode_request(self, node_pydra):
        """
        Request a cloud instance be booted.  The instance is automatically added as a pydra node after the hostname is received.
        """
        service = node_pydra.service_provider
        logger.info("Creating " + service  + " node.")
        #wait for image and size options to be retrieved
        if not self.image[service] or not self.size:
            sleep(5)
            logger.info("Waiting on size or image.")
        node_libcloud = self.conn[service].create_node(name='Pydra', image=self.image[service], size=self.size, ex_securitygroup="Pydra")
        logger.info("Node created, name: " + node_libcloud.name)
        logger.info("Waiting for hostname.")
        while node_libcloud.public_ip==['']:
            sleep(15)
            node_libcloud = [node for node in self.conn[service].list_nodes() if node.name==node_libcloud.name][0]
        logger.info("Got hostname..")
        
        self.cloudnode_create(node_libcloud, node_pydra)

    def cloudnode_create(self, node_libcloud, node_pydra):
        """
        Update booted cloud instance's information.
        """
        logger.info("Updating cloud node..")
        update_values = {'id': str(node_pydra.id), 'host': str(node_libcloud.public_ip[0]), 'port': str(pydra_settings.PORT), 'security_group': "Pydra"}
        try:
            self.cloudnode_edit(update_values)
        except Exception, e:
            logger.error("CloudNode hostname could not be updated.")

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
        service = pydra_node.service_provider
        try:
            node_libcloud = [node for node in self.conn[service].list_nodes() if node.name==node_pydra.name][0]
            self.conn[service].destroy_node(node_libcloud)
            logger.info("CloudNode instance " + node_libcloud.name + " terminated.")
        except:
            logger.warning("CloudNode instance could not be terminated.  Instance must be terminated manually.")

    def cloudnode_edit(self, values):
        """
        Updates or creates a CloudNode with the values passed in.  If an id field
        is present it will be update the existing CloudNode.  Otherwise it will
        create a new CloudNode.
        """
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

        if new:
            node.host = "Booting..."
            node.save()
            self.cloudnode_request(node)
        else:            
            self.emit('NODE_UPDATED', node)
        
    def list_cloudnodes(self):
        """
        Lists nodes available from all service providers (not necessarily added as pydra nodes)
        """
        #return list of public ip's not node objects
        nodes = []
        for v in self.conn.values():
            nodes += [node.public_ip for node in v.list_nodes() if node.name=='Pydra']
        return nodes
