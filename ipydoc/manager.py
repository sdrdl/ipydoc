"""Top Object for managing containers

Copyright (c) 2014 San Diego Regional Data Library. This file is licensed under the terms of the
Revised BSD License, included in this distribution as LICENSE.txt
"""


#Using the docker python library: https://github.com/dotcloud/docker-py

from docker.client import APIError
import logging

class Container(object):

    def __init__(self, manager, user, container):
        self.manager = manager
        self.user = user
        self.container = container

    def kill(self):
        return self.manager.kill(self.user)

    def start(self, port):
        return self.manager.start(self.user, port)

    def inspect(self):
        return self.manager.inspect(self.user)


class RedisManager(object):

    def __init__(self, proxy_config, host='localhost', port = 6379, db = 0):
        import redis
        self.client = redis.StrictRedis(host=host , port=port, db=db)
        self.pc = proxy_config

    def _make_key(self, name):
        return 'frontend:{}.{}'.format(name,self.pc.base_domain)



    def _make_name(self, name):
        return '{}{}'.format(self.pc.name_prefix, name)

    def stub(self,user):
        """Point the proxy address to the stub"""
        """Point the proxy address to the stub"""
        self.ensure_frontend_only(user)

    def activate(self, user, ip=None):

        self.ensure_frontend_only(user)

        port = self.port(user)

        if not ip:
            ip = self.pc.common_ip

        backend = 'http://{}:{}'.format(ip, port)

        self.client.rpush(self._make_key(user), backend)

    def ensure_frontend_only(self, user):
        """Ensure that only the first item is in the list, the one that has the
        name of the frontend. """
        key = self._make_key(user)

        l = self.client.llen(key)

        if l == 0: # Key doesn't exists, so make frontend entry:
            self.client.rpush(key, self._make_name(user) )
        elif l == 1: # Already what we want
            pass
        else:
            self.client.ltrim(key, 0, 0)

        # Assign a port offset to every user.
        self.port(user)

    def port(self, user):

        offset =  self.client.hget('ipy:port', user)

        if not offset:
            port = self.client.incr('ipy:port:last')
            self.client.hsetnx('ipy:port', user, port)

            # Weak protection against contention
            offset =  self.client.hget('ipy:port', user)

        return int(offset)+self.pc.base_port


class DockerManager(object):
    
    client = None
    container_prefix = 'ipy_'

    def __init__(self, client_ref, image):
    
        self.image = image
        self.client_ref = client_ref

        self.client = self.client_ref.open()

        self.logger = logging.getLogger(__name__)


    def _user_to_c_name(self, user):
        return self.container_prefix+user

    def _user_to_c_id(self, user):

        try:
            insp = self.client.inspect_container(self._user_to_c_name(user))

            return insp['ID']

        except APIError:
            return None

    def inspect(self,user):

        return self.client.inspect_container(self._user_to_c_name(user))

    def kill(self,user):
        container_name = self._user_to_c_name(user)

        try:
            insp = self.client.inspect_container(container_name)
        except APIError:
            return False

        container_id = insp['ID']

        if insp['State']['Running']:
            self.logger.debug("Killing {}".format(container_name))
            self.client.kill(container_id)

        self.client.remove_container(container_id)

        self.logger.debug("Removing {}".format(container_name))

        return True

    def create(self, user, env={}):
        '''Ensure that a container for the user exists'''
        container_name = self._user_to_c_name(user)

        try:
            cont = self.client.create_container(self.image, detach=True, name = container_name,
                                      ports = [8888], environment=env, volumes = ['/notebooks'])
        except APIError:
            insp = self.client.inspect_container(container_name)
            cont = insp['ID']

        return Container(self,user, cont)
    
        # command=None, hostname=None, user=None,
        #               stdin_open=False, tty=False, mem_limit=0,
        #               ports=None, environment=None, dns=None, volumes=None,
        #               volumes_from=None, network_disabled=False, name=None,
        #               entrypoint=None, cpu_shares=None, working_dir=None,
        #               memswap_limit=0)
    
    def start(self, user, port):
        container_name = self._user_to_c_name(user)

        try:
            insp = self.client.inspect_container(container_name)
     
            if insp['State']['Running']:
                self.logger.debug('Container {} is running'.format(container_name))

            else:
                self.logger.debug('Starting {}'.format(container_name))
            
                external = '/proj/notebooks/{}/'.format(user)
                internal = '/notebooks'
            
                binds = { external :{
                            'bind': internal, 
                            'ro': False
                            } 
                        }
                    
                binds = {
                    external: internal
                }

                self.client.start(insp['ID'],  port_bindings={8888:port}, binds = binds )
                        #lxc_conf=None,
                        #publish_all_ports=False, links=None, privileged=False,
                        #dns=None, dns_search=None, volumes_from=None, network_mode=None)
            
        except APIError as e:
            print e

        return insp['Config']['Env']

class GitManager(object):
    """Clone, push, pull and watch a user's git repo"""

    def __init__(self, config, user, username, password):
        self.config = config
        self.user = user
        self.username = username # The Github username
        self.password = password

    @property
    def user_dir(self):
        import os
        return os.path.join(self.config.user_dir, self.user)

    def start(self, user):
        """Clone or pull a repo"""
        pass

    def stop(self, user):
        """Stop the observer and push the repo"""
        pass


    def watch(self):

        pass





class Director(object):
    """The Director coordinates the operation of the maangers. """
    def __init__(self, docker, redis):

        self.docker = docker
        self.redis = redis

    def start(self, user, repo_url=None, github_auth=None):
        from IPython.lib import passwd
        from random import choice
        import string

        password = ''.join([choice(string.letters + string.digits) for i in range(12)])

        c = self.docker.create(user, env={
            'IPYTHON_COOKIE_SECRET': passwd(password),
            'IPYTHON_PASSWORD': passwd(password),
            'IPYTHON_CLEAR_PASSWORD': password,
            'IPYTHON_REPO_URL': repo_url,
            'IPYTHON_REPO_AUTH': github_auth
        })

        env = c.start(self.redis.port(user))

        self.redis.activate(user)

        for e in env:
            k,v = e.split('=',1)
            if k == 'IPYTHON_CLEAR_PASSWORD':
                return v


    def stop(self, user):

        self.redis.stub(user)
        try:
            self.docker.kill(user)
        except APIError:
            pass


