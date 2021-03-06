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

    def _make_key(self, name=None):

        if name:
            return 'frontend:{}.{}'.format(name,self.pc.base_domain)
        else:
            return 'frontend:{}'.format(self.pc.base_domain)


    def _make_name(self, name=None):

        if not name:
            name = '_director' # For the

        return '{}{}'.format(self.pc.name_prefix, name)

    def stub(self,user, backend):
        """Point the proxy address to the stub"""
        """Point the proxy address to the stub"""
        self.ensure_frontend_only(user)

        return self.set_backend(user, backend)

    def activate(self, user, ip=None):

        self.ensure_frontend_only(user)

        port = self.port(user)

        if not ip:
            ip = self.pc.common_ip

        backend = 'http://{}:{}'.format(ip, port)

        return self.set_backend(user, backend)


    def set_backend(self, user, url):

        self.client.rpush(self._make_key(user), url)

    def ensure_frontend_only(self, user=None):
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
        if user:
            self.port(user)

    def activate_dispatcher(self, url):
        """Setup the front and backends for the dispatcher"""

        self.ensure_frontend_only()

        self.client.rpush(self._make_key(), url)


    def port(self, user):
        '''Get the host port assigned to the user'''
        offset =  self.client.hget('ipy:port', user)

        if not offset:
            port = self.client.incr('ipy:port:last')
            self.client.hsetnx('ipy:port', user, port)

            # Weak protection against contention
            offset =  self.client.hget('ipy:port', user)

        return int(offset)+self.pc.base_port

    def record_repo(self, repo_url):
        """Keep track of notebook repos so we can display them later in nbviewer. """
        offset = self.client.sadd('ipy:all_repos', repo_url)

    def record_user(self, user):
        """Keep track of notebook users so we can display them later in nbviewer. """
        offset = self.client.sadd('ipy:all_users', user)

class DockerManager(object):
    
    client = None
    container_prefix = 'ipynb_'

    dispatcher_image = 'ipynb_dispatcher'
    dispatcher_container_name = 'ipynb_dispatcher'

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

    def get_host_for_user(self, user):
        return self._user_to_c_id(user)

    def get_user_for_host(self, host_id):

        try:
            insp = self.client.inspect_container(host_id)
        except APIError:
            return False

        name = insp['Name'].replace(self.container_prefix, '').strip('/')

        return name

    def inspect(self,user):

        return self.client.inspect_container(self._user_to_c_name(user))

    def kill(self,user=None, host_id=None):

        if host_id is None:
            host_id = self._user_to_c_name(user)

        try:
            insp = self.client.inspect_container(host_id)
        except APIError:
            return False

        container_id = insp['ID']

        if insp['State']['Running']:
            self.logger.debug("Killing {}".format(host_id))
            self.client.kill(container_id)

        self.client.remove_container(container_id)

        self.logger.debug("Removing {}".format(host_id))

        return container_id


    def create(self, user, env={}):
        '''Ensure that a container for the user exists'''
        import os

        container_name = self._user_to_c_name(user)

        try:

            cont = self.client.create_container(self.image,
                                                detach=True,
                                                name = container_name,
                                                ports = [8888],
                                                #volumes_from=os.getenv('VOLUMES_NAME', None),
                                                environment=env)
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
        import os


        container_name = self._user_to_c_name(user)

        try:
            insp = self.client.inspect_container(container_name)
     
            if insp['State']['Running']:
                self.logger.debug('Container {} is running'.format(container_name))

            else:
                self.logger.debug('Starting {}'.format(container_name))
            

                #binds = {'/proj/notebooks/{}/'.format(user): '/notebooks'}
                binds = None

                host_id = os.getenv('HOSTNAME', False)

                if host_id:
                    host_name = self.client.inspect_container(host_id)["Name"]
                    links = [( host_name, 'director')]
                else:
                    links = None


                self.client.start(insp['ID'],  port_bindings={8888:port}, binds = binds, links = links)
                        #lxc_conf=None,
                        #publish_all_ports=False, links=None, privileed=False,
                        #dns=None, dns_search=None, volumes_from=None, network_mode=None)
            
        except APIError as e:
            print e


        return insp['Config']['Env']

    def stop_dispatcher(self):
        """Stop the dispatcher, and any remaining ipython containers. """
        id = self.kill(host_id=self.dispatcher_container_name)

        for c in self.client.containers():
            for name in c['Names']:

                name = str(name)

                if 'director' in  name:
                    break

                if '/'+self.container_prefix in name:
                    self.logger.debug("Killing "+name)
                    self.kill(host_id=c['Id'])
                    break


    def start_dispatcher(self, director_port=False):
        import os
        import socket



        if director_port and director_port is not False:
            env = {'DIRECTOR_PORT' : director_port}

        elif director_port:
            connect = "tcp://{}:4242".format(socket.gethostbyname(socket.gethostname()))

            env = {'DIRECTOR_PORT' : connect}
        else:

            env = {}

        self.stop_dispatcher()

        try:

            cont = self.client.create_container(self.dispatcher_image,
                                                detach=True,
                                                name=self.dispatcher_container_name,
                                                tty=True,
                                                stdin_open=True,
                                                ports=[8000],
                                                #volumes_from=os.getenv('VOLUMES_NAME', None),
                                                environment=env)

            insp = self.client.inspect_container(self.dispatcher_container_name)

        except APIError as e:
            # It already exists, possibly. There are many other errors on the same class.

            insp = self.client.inspect_container(self.dispatcher_container_name)

        try:

            if insp['State']['Running']:
                self.logger.debug('Container {} is running'.format(self.dispatcher_container_name))

            else:
                self.logger.debug('Starting {}'.format(self.dispatcher_container_name))

                links = None

                if director_port is False: # Assume we are running in a docker container
                    import os

                    try:
                        local_insp = self.client.inspect_container(os.getenv('HOSTNAME'))
                    except APIError as e:
                        raise Exception("Failed to get HOSTNAME or director_port configuration");

                    links = { local_insp['Name'].strip('/'):'director'}

                self.logger.debug('Running dispatcher {} with links {}'.format(insp['ID'], links))

                self.client.start(insp['ID'], publish_all_ports=True, links = links)

                #lxc_conf=None,
                #publish_all_ports=False, links=None, privileed=False,
                #dns=None, dns_search=None, volumes_from=None, network_mode=None)

        except APIError as e:
            raise
            print e

        return insp['Config']['Env']

    def is_running(self, id):
        '''Return true if the container is running, where id is either the host id or the username for the
        ipython container '''
        import requests
        import time

        use_id = None

        try:
            # Try a username
            container_name = self._user_to_c_name(id)

            insp = self.client.inspect_container(container_name)
            used_id = container_name
        except APIError as e:
            try:
                # Nope, try a host_id
                insp = self.client.inspect_container(id)
                used_id = id
            except APIError as e:
                return False

        if not insp['State']['Running']:
            return False

        # The container is running, so now we have to check for IPython to be running.
        port = self.ports(insp['ID'])[0]

        url = "http://{}:{}".format(port.h_address, int(port.h_port))

        retries = 12
        for i in range(retries):
            try:
                r = requests.get(url)
                if r.status_code == 200:
                    break
            except requests.ConnectionError:
                time.sleep(.25)
                continue

        if i == retries-1:
            return False
        else:
            return True




    def ports(self, host_id):
        insp = self.client.inspect_container(host_id)

        import pprint
        import urlparse
        import collections
        Ports = collections.namedtuple("Ports", ["c_port", "h_address", "h_port"], verbose=False, rename=False)

        ports = []

        ext_host_ip = urlparse.urlparse(self.client_ref.url)[1].split(':', 1)[0]

        for port, host_addresses in insp['NetworkSettings']['Ports'].items():

            for host_address in host_addresses:
                ports.append(Ports(port,
                             host_address['HostIp'] if host_address['HostIp']  != '0.0.0.0' else ext_host_ip,
                             host_address['HostPort']))

        return  ports





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
        self.dispatcher_url = None

    def init(self, director_port=False):

        self.docker.start_dispatcher(director_port = director_port)

    def start(self, user, repo_url=None, github_auth=None, github_email=None, github_name=None):
        from IPython.lib import passwd
        from random import choice
        import string

        password = ''.join([choice(string.letters + string.digits) for i in range(12)])

        c = self.docker.create(user, env={
            'IPYTHON_COOKIE_SECRET': passwd(password),
            'IPYTHON_PASSWORD': passwd(password),
            'IPYTHON_CLEAR_PASSWORD': password,
            'IPYTHON_REPO_URL': repo_url,
            'IPYTHON_REPO_AUTH': github_auth,
            'GITHUB_EMAIL': github_email,
            'GITHUB_NAME': github_name,
            'GITHUB_USER': user,
            })

        env = c.start(self.redis.port(user))

        self.redis.activate(user)

        # Keep track of the github repos that are used in the system, so we can references them in
        # nbviewer.
        self.redis.record_repo(repo_url)
        self.redis.record_user(user)

        for e in env:
            k,v = e.split('=',1)
            if k == 'IPYTHON_CLEAR_PASSWORD':
                return v

    def stop(self, name):

        host_id = self.docker.get_host_for_user(name)

        if not host_id:
            host_id = name

        self.logout(host_id)

        try:
            self.docker.kill(host_id=host_id)
        except APIError as e:
            print e
            pass

    def is_running(self, id):
        return self.docker.is_running(id)

    def logout(self, host_id):
        """Move the proxy entry for the user back to the dispatcher"""

        user = self.docker.get_user_for_host(host_id)

        self.redis.stub(user, self.dispatcher_url)

    def activate_dispatcher(self, host_id):

        port =  self.docker.ports(host_id)[0]

        self.dispatcher_url = 'http://{}:{}'.format(port.h_address, port.h_port)

        self.redis.activate_dispatcher(self.dispatcher_url )
