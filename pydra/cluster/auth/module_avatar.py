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

from twisted.spread import pb

import logging
logger = logging.getLogger('root')


class RemoteWrapper():
    """
    Wrapper for remote methods to add the Avatar to the method call
    """

    def __init__(self, avatar, remote):
        self.avatar = avatar

        # process remote - it may be just a function or a tuple
        # containing a function and additional options
        if isinstance(remote, (list,tuple)):
            self.function, self.secure = remote
        else:
            self.function = remote
            self.secure = True


    def __call__(self, *args, **kwargs):
        """
        Calls original function, adding the avatar to the beginning of the args
        """
        if self.secure and not self.avatar.authenticated:
            logger.error('Attempted access to secured method before authentication: %s - %s', (self.avatar.name, self.function))
            return

        return self.function(self.avatar.name, *args, **kwargs)


class ModuleAvatar(pb.Avatar):
    """
    Avatar that aggregates methods exposed by Pydra Modules.  The methods will
    be stored in a dictionary mapping the method names back to the module that
    exposed them
    """

    _manager = None

    def __init__(self, remotes, *args, **kwargs):
        self._remotes = remotes


    def __getattr__(self, key):
        """
        Overridden to lookup remoted methods from modules
        """

        # proxy perspective methods through the _remotes.
        if 'perspective_' == key[:12]:
            
            # remotes must be packaged in wrapper so that there is a link
            # back to the worker that called it.  Remotes cannot be wrapped
            # in the list because the wrapper is implementation specific
            try:
                return RemoteWrapper(self, self._remotes[key[12:]])
            except KeyError:
                logger.error('Avatar [%s] tried to call non-existant function: %s' % (self.name, key[12:]))
                raise Exception('Avatar [%s] tried to call non-existant function: %s' % (self.name, key[12:]))

        return pb.Avatar.__getattr__(key)
