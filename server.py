#!/usr/bin/env python
# -*- coding: utf-8 -

import functools
import logging
import json
import uuid
import yaml

from tornado.ioloop import IOLoop, PeriodicCallback
from tornado.web import RequestHandler, Application
from tornado.websocket import WebSocketHandler


logging.basicConfig(level=logging.INFO,
format='%(asctime)s - %(message)s',
datefmt='%Y-%m-%d %H:%M:%S')


LISTENERS = []
HOSTS = {}
ioloop = IOLoop.instance()

config = yaml.load(open('config.yaml', 'r').read())


class Offering(object):
    def __init__(self, **kwargs):
        [setattr(self, k, v)
            for (k, v) in kwargs.items()]

    def __str__(self):
        return str(self.name)

    def __hash__(self):
        return hash(str(self))

    def __cmp__(self, other):
        return cmp(str(self), str(other))


offerings = [Offering(**i)
    for i in config['offerings']]
offerings_lookup = dict([(str(i), i) for i in offerings])


class Host(object):
    def __init__(self, id):
        self.id = id
        self.vms = []
        self.numcpus = config['host']['numcpus']
        self.mem = config['host']['mem']

    def __iter__(self):
        return iter(self.vms)

    def append(self, item):
        o = offerings_lookup[item['so']]
        self.numcpus -= o.numcpus
        self.mem -= o.mem
        if self.numcpus == 0 or self.mem == 0:
            send_message({'action': 'capacity',
                'key': self.id})
            self.numcpus += o.numcpus
            self.mem += o.mem
        else:
            self.vms.append(item)


def send_message(data):
    logging.debug('sending message to listeners: %s' % repr(data))
    msg = unicode(json.dumps(data))
    for i in LISTENERS:
        i.write_message(msg)
    #TODO: send to rabbitmq


def status_message(_key):
    for k, v in HOSTS.items():
        send_message({
            'action': 'stats',
            'key': k,
            'numcpus': (config['host']['numcpus'] - v.numcpus),
            'mem': (float(v.mem) / float(config['host']['mem']))*100 })


def create_host():
    logging.info('adding host')
    _key = str(uuid.uuid4())
    HOSTS.update({_key: Host(_key)})
    send_message({'action': 'new_host', 'key': _key})

    cb = functools.partial(send_message,
        {'action': 'hb', 'key': _key})
    PeriodicCallback(cb, 3 * 1000, ioloop).start()
    status = functools.partial(status_message, _key)
    PeriodicCallback(status, 3 * 1000, ioloop).start()


def create_vm(_key, so):
    logging.info('added vm')
    vm = {'so': so, 'key': str(uuid.uuid4())}
    HOSTS.get(_key).append(vm)
    send_message({'key': _key,
        'vm': vm, 'action': 'vm'})


class MainHandler(RequestHandler):
    def get(self):
        self.render("index.html",
            title="Host simulator",
            path='localhost:8888',
            offerings=offerings)

    def post(self):
        action = self.request.arguments['action'][0]

        if action == 'host':
            create_host()
        elif action == 'vm':
            host = self.request.arguments['host'][0]
            so = self.request.arguments['so'][0]
            create_vm(host, so)


class RealTimeHandler(WebSocketHandler):
    def open(self):
        LISTENERS.append(self)

        def init_stack():
            for k, v in HOSTS.items():
                yield {'action': 'new_host', 'key': k}
                for vm in v:
                    yield {'key': k, 'action': 'vm', 'vm': vm}

        for data in init_stack():
            self.write_message(unicode(json.dumps(data)))

    def on_message(self, message):
        pass

    def on_close(self):
        LISTENERS.remove(self)


application = Application([
    (r"/", MainHandler),
    (r"/actions/", RealTimeHandler),
])


if __name__ == "__main__":
    application.listen(8888)
    ioloop.start()
