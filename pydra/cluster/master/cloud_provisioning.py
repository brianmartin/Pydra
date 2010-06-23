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
        'NODE_UPDATED',
    ]

    _shared = []

    def __init__(self):
        self._interfaces = [
            self.cloudnode_delete,
            self.cloudnode_detail,
            self.cloudnode_edit,
            self.cloudnode_info_sizes,
            self.cloudnode_info_providers,
        ]
        self._listeners = {'MANAGER_INIT':self.cloud}

    def cloud(self, callback=None):
        """
        Initialize and connect to services for which credentials are provided in pydra_settings.
        """

        #To add cloud service providers, simply define a description and crednames below.
        #Crednames can be in any order and are keywords for the specific libcloud Driver.
        #Crednames should then also be added to pydra_settings in addition to the preferred image id: SERVICE_IMAGE.
        #Valid keywords are: id (used internally), secret, host, port, and secure
        #As of last update, undefined libcloud drivers include:
        #    GOGRID, VPSNET, VCLOUD, RIMUHOSTING, ECP, IBM, OPENNEBULA, DREAMHOST
        #    (these may be easily added but I don't want to add too many I can't test..)

        self.descriptions = {'EC2': 'Amazon EC2',
                             'EUCALYPTUS': 'Eucalyptus Cloud',
                             'RACKSPACE': 'Rackspace Cloud (Mosso)',
                             'SLICEHOST': 'Slicehost',
                             'LINODE': 'Linode',
                             }        
        self.crednames = {'EC2': {'id': 'EC2_ACCESS_ID', 'secret': 'EC2_SECRET_KEY'},
                      'EUCALYPTUS': {'id': 'EUCALYPTUS_ACCESS_ID', 'secret':'EUCALYPTUS_SECRET_KEY', 'host': 'EUCALYPTUS_HOST'},
                      'RACKSPACE': {'id': 'RACKSPACE_USER', 'secret': 'RACKSPACE_API'},    
                      'SLICEHOST': {'id': 'SLICEHOST_USER', 'secret': 'SLICEHOST_SECRET_KEY'},
                      'LINODE': {'id': 'LINODE_USER', 'secret': 'LINODE_SECRET_KEY'},
                      }

        self.creds = {}
        self.conn = {}
        self.image = {}
        self.sizes = {}
        
        self.connect_all()

    def connect_all(self):
        """
        Connect to all services for which credentials are defined.
        """
        self.verify_creds()
        for service in self.creds.keys():
            Thread(target=self.connect, args=[service,]).start()

    def verify_creds(self):
        """
        Read in all credentials that are defined in pydra_settings and are not empty.
        """
        for service in self.crednames.keys():
            if all(map(lambda x: hasattr(pydra_settings, x) and eval('pydra_settings.' + x) != '', self.crednames[service].values())):
                #'id' can't be in the dict because it cannot be passed to libcloud as a kwarg
                self.creds[service] = [eval('pydra_settings.' + self.crednames[service]['id']), \
                                       dict([(k, eval('pydra_settings.' + v)) for k,v in self.crednames[service].iteritems() if k != 'id'])]

    def connect(self, service):
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
        self.get_images(service)
        self.get_sizes(service)
        self.add_booted_nodes(service)
                
    def get_images(self, service):
        """
        Store image list from specified service.
        """
        try:
            logger.info("Retrieving " + service + " image list...")
            self.image[service] = filter(lambda x: x.id == eval('pydra_settings.' + service + '_IMAGE_ID'), self.conn[service].list_images())[0]
            logger.info("Got " + service + " image list, and found Pydra image.")
        except:
            logger.warning(service + " image list not received or Pydra image not found.")

    def get_sizes(self, service):
        """
        Store list of instance sizes available from specified service.
        """
        try:
            self.sizes[service] = {}
            for size in self.conn[service].list_sizes():
                self.sizes[service][size.id] = size
        except:
            logger.warning(service + " size list not received.")
        
    def create_security_group(self):
        """
        Check for the Pydra EC2 security group.
        This policy is entirely permissive (all ports open) as this is the only way to specify using libcloud.
        """
        try:
            self.conn.ex_create_security_group("Pydra", "Permissive security group for Pydra cloud provisioning.")
            self.conn.ex_authorize_security_group_permissive("Pydra")
            logger.info("Amazon EC2 security group created.")
        except:
            logger.info("Amazon EC2 security group already created.")
            
    def add_booted_nodes(self, service):
        """
        Add available instances that have already been booted to the Pydra db.
        This is useful if the Master is restarted.
        """
        for node_libcloud in self.conn[service].list_nodes():
            #if already added or still booting: don't add
            try:
                CloudNode.objects.get(name=node_libcloud.name)
            except:
                if not node_libcloud.public_ip == ['']:
                    self.cloudnode_edit({'host': str(node_libcloud.public_ip[0]), 'service_provider': service})
        
    def cloudnode_request(self, node_pydra):
        """
        Request a cloud instance be booted (threaded).  The instance is automatically added as a pydra node after the hostname is received.
        """
        def _cloudnode_request(node_pydra):
            service = node_pydra.service_provider
            logger.info("Creating " + service  + " node.")

            node_libcloud = self.conn[service].create_node(name='Pydra' + str(node_pydra.id), image=self.image[service], size=self.sizes[service][node_pydra.instance_size])
            logger.info("Node created, name: " + node_libcloud.name)
            logger.info("Waiting for hostname.")
            while node_libcloud.public_ip == ['']:
                sleep(15)
                node_libcloud = [node for node in self.conn[service].list_nodes() if node.name==node_libcloud.name][0]
            logger.info("Got hostname..")
        
            #Update booted cloud instance's information.
            try:
                update_values = {'id': str(node_pydra.id), 'host': str(node_libcloud.public_ip[0]), 'port': str(pydra_settings.PORT), 'service': service}
                self.cloudnode_edit(update_values)
                logger.info("Updating cloud node..")
            except Exception, e:
                logger.error("CloudNode hostname could not be updated.")

        Thread(target=_cloudnode_request, args=(node_pydra,)).start()

    def cloudnode_delete(self, id):
        """
        Deletes and destroys a CloudNode.
        """
        node_pydra = CloudNode.objects.get(id=id)

        def destroy_instance(node_pydra):
            service = node_pydra.service_provider
            try:
                node_libcloud = [node for node in self.conn[service].list_nodes() if node.name==node_pydra.name][0]
                self.conn[service].destroy_node(node_libcloud)
                logger.info("CloudNode instance " + node_libcloud.name + " terminated.")
            except:
                logger.warning("CloudNode instance could not be terminated.  Instance must be terminated manually.")

        Thread(target=destroy_instance, args=[node_pydra,]).start()

        node_pydra.deleted = True
        node_pydra.save()
        self.emit('NODE_DELETED', node_pydra)

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
            #if hostname is already given (and not empty), don't request instance because we already have one to add!
            try:
                if values['host'] != '':
                    self.emit('NODE_CREATED', node)
                    logger.info("Node created using hostname: " + values['host'])
                else:
                    raise KeyError
            #otherwise request a new instance
            except KeyError:
                node.host = "Booting..."
                node.save()
                self.cloudnode_request(node)
        else:            
            self.emit('NODE_UPDATED', node)

    def cloudnode_detail(self, id):
        """
        Returns details for a single cloudnode
        """
        cloudnode = CloudNode.objects.get(id=id)
        return cloudnode.json_safe()

    def cloudnode_info_sizes(self, service_provider):
        """
        Returns available sizes for the given service_provider
        """
        return [{'id': size_id, 'description': size.name} for (size_id, size) in self.sizes[service_provider].items()]

    def cloudnode_info_providers(self):
        """
        Returns available providers
        """
        return [{'id': service_provider, 'description': self.descriptions[service_provider]} for service_provider in self.conn.keys()]
