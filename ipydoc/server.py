"""ZeroRPC server for running the director

Copyright (c) 2014 San Diego Regional Data Library. This file is licensed under the terms of the
Revised BSD License, included in this distribution as LICENSE.txt
"""


import zerorpc
import argparse
import logging
from ipydoc import ProxyConfig, DockerClientRef
from manager import DockerManager, RedisManager, Director

class DockerServer(object):

    def __init__(self, director, logger):
        self.director = director
        self.logger = logger


    def version(self):
        import ipydoc
        return ipydoc.__version__

    def start(self, user, repo_url=None, github_auth=None):
        self.logger.info("Starting {}".format(user))
        return self.director.start(user, repo_url=repo_url, github_auth=github_auth)

    def stop(self, user):
        self.logger.info("Stopping {}".format(user))
        return self.director.stop(user)


if __name__ == '__main__':
    import os
    import urlparse

    docker_connect =  os.getenv('DOCKER_HOST', 'tcp://0.0.0.0:4243')

    parser = argparse.ArgumentParser(description='Serve requests to start ipython containers',
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)

    parser.add_argument('-d', '--debug', action='store_true', help='turn on debugging')
    parser.add_argument('-p', '--port', type=int, default=4242, help='TCP Port to use')
    parser.add_argument('-H', '--host', default='0.0.0.0', type=str, help='Host IP address to attach to ')
    parser.add_argument('-D', '--docker', default= docker_connect,type=str, help='Connection URL to the docker host')

    parser.add_argument('-P', '--proxy-domain', type=str, required=True, help='Base domain for the proxy')
    parser.add_argument('-b', '--backend-host', type=str, help='Host address of the ipython containers, usually the docker host')
    parser.add_argument('-I', '--image', type=str, default='ipynb_ipython', help='Name of docker images for ipython container')

    parser.add_argument('-R', '--redis', type=str, required=True, help='Redis host')

    args = parser.parse_args()

    logger = logging.getLogger(__name__)

    if not args.backend_host:
        parts = urlparse.urlparse(args.docker)

        backend_host = parts.netloc.split(':')[0]
    else:
        backend_host = args.backend_host

    if args.debug:
        logging.basicConfig()
        logger.setLevel(logging.DEBUG)

    redis_ = RedisManager(ProxyConfig(args.proxy_domain, backend_host), args.redis)

    docker = DockerManager(DockerClientRef(args.docker,'1.9', 10), args.image)

    d = Director(docker, redis_)

    print 'Starting on {}:{}'.format(args.host, args.port)
    s = zerorpc.Server(DockerServer(d, logger))
    s.bind("tcp://{}:{}".format(args.host, args.port))
    s.run()