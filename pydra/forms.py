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

from django import forms
from django.forms import ModelForm

from models import Node, CloudNode

"""
Form used when editing nodes
"""
class NodeForm(ModelForm):
    class Meta:
        model = Node
        exclude=('key', 'seen', 'pub_key', 'priv_key')

    cores_available = forms.IntegerField(required=False)
    cores           = forms.IntegerField(required=False)
    stones          = forms.IntegerField(required=False)
    total_memory    = forms.IntegerField(required=False)
    avail_memory    = forms.IntegerField(required=False)


"""
Form used when editing cloudnodes
"""
class CloudNodeForm(NodeForm):
    class Meta:
        model = CloudNode
        exclude=('key', 'seen', 'pub_key', 'priv_key')

    service_provider= forms.CharField(max_length=255)
    name            = forms.CharField(max_length=255, required=False)
    instance_size   = forms.CharField(max_length=255, required=False)
    instance_image  = forms.CharField(max_length=255, required=False)
    security_group  = forms.CharField(max_length=255, required=False)
    host            = forms.CharField(required=False)

