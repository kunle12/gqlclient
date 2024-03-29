from six.moves import urllib
import string
import random
import json
import time
import threading
import ssl
import websocket
import certifi

class GraphQLClient(object):
    def __init__(self, endpoint, certcheck = True):
        self._endpoint = endpoint
        self._token = None
        self._headername = None
        self._certcheck = certcheck

    def execute(self, query, variables=None):
        return self._send(query, variables)

    def inject_token(self, token, headername='Authorization'):
        self._token = token
        self._headername = headername

    def _send(self, query, variables):
        data = {'query': query,
                'variables': variables}
        headers = {'Accept': 'application/json',
                   'Content-Type': 'application/json'}

        if self._token is not None:
            headers[self._headername] = '{}'.format(self._token)

        req = urllib.request.Request(self._endpoint, json.dumps(data).encode('utf-8'), headers)

        try:
            if self._certcheck:
                context = ssl.create_default_context(cafile=certifi.where())
            else:
                context = ssl._create_unverified_context()
            response = urllib.request.urlopen(req, context=context)
            return response.read().decode('utf-8')
        except urllib.error.HTTPError as e:
            print((e.read()))
            print('')
            raise e

class GraphQLSubscriptionClient(object):
    """
    A simple GraphQL client that works over Websocket as the transport
    protocol, instead of HTTP.
    This follows the Apollo protocol.
    https://github.com/apollographql/subscriptions-transport-ws/blob/master/PROTOCOL.md
    """

    def __init__(self, url, certcheck = True, reconnect = True):
        self._url = url
        self._certcheck = certcheck
        self._sub_thread = None
        self._reconnect = reconnect
        self._subscriptions = {} #id/handler mapping
        self._init_connection()

    def _init_connection(self):
        try:
            if self._certcheck:
                self._conn = websocket.create_connection(self._url)
            else:
                self._conn = websocket.create_connection(self._url,
                                                    sslopt={"cert_reqs": ssl.CERT_NONE})
        except Exception as e:
            print("Unable to create websocket connection on {}, error {}".format(self._url, e))
            self._conn = None
            return False

        ack = self._conn_init()
        if not ack or ack['type'] == 'connection_error':
            print("Unable to initiate GraphQL connection on websocket for {}".format(self._url))
            self._conn.close()
            self._conn = None
            return False
        return True

    def _conn_init(self, headers=None):
        payload = {
            'type': 'connection_init',
            'payload': {'headers': headers}
        }
        retdata = None
        try:
            self._conn.send(json.dumps(payload))
            retdata = self._conn.recv()
        except:
            return None
        return json.loads(retdata)

    def _conn_term(self, headers=None):
        payload = {
            'type': 'connection_terminate',
            'payload': {'headers': headers}
        }
        try:
            self._conn.send(json.dumps(payload))
        except:
            pass

    def _start(self, payload):
        if not self._conn:
            return None
        # generate random alphanumeric id
        def gen_id(size=6, chars=string.ascii_letters + string.digits):
            return ''.join(random.choice(chars) for _ in range(size))

        _id = gen_id()
        frame = {'id': _id, 'type': 'start', 'payload': payload}
        try:
            self._conn.send(json.dumps(frame))
        except:
            print("Unable to start GraphQL subscription connection")
            return None
        return _id

    def _stop(self, _id):
        payload = {'id': _id, 'type': 'stop'}
        try:
            self._conn.send(json.dumps(payload))
        except:
            pass

    def _rebuild_connection(self):
        print("reestablishing websocket connection to {}".format(self._url))
        if self._init_connection():
            # reestablish subscriptions
            new_subscription = {}
            for cb,payload in self._subscriptions.values():
                _id = self._start(payload)
                if not _id:
                    continue
                new_subscription[_id] = (cb, payload)
            self._subscriptions = new_subscription

    def _on_message(self, message):
        data = json.loads(message)
        # skip keepalive messages
        if data['type'] != 'ka':
            print("message received: {}".format(message))

    def _sub_loop(self):
        while True:
            _lock = threading.Lock()
            with _lock:
                running = (len(self._subscriptions) > 0)

            if not running:
                break
            if self._conn is None: #caused by disconnection
                time.sleep(1.0)
                self._rebuild_connection()
                continue
            try:
                retdata = self._conn.recv()
                r = json.loads(retdata)
            except:
                if self._reconnect:
                    self._rebuild_connection()
                    continue
                else:
                    print("Remote websocket closed, disable the client")
                    self._subscriptions = {}
                    self._conn = None
                    self._sub_thread = None
                    break
            #print(r)
            if r['type'] != 'ka' and r['id'] in self._subscriptions:
                if r['type'] == 'error':
                    print("subscription id {} error".format(r['id']))
                    self.unsubscribe(r['id'])
                elif r['type'] == 'complete':
                    print("subscription id {} complete".format(r['id']))
                else:
                    self._subscriptions[r['id']][0](r)
            time.sleep(0.2)

    def subscribe(self, query, variables=None, headers=None, callback=None):
        if not self._conn:
            return None
        if callback is not None and not callable(callback):
            print("Invalid callback for subscription {}".format(query))
            return None

        payload = {'headers': headers, 'query': query, 'variables': variables}
        _id = self._start(payload)
        if not _id:
            return _id
        _lock = threading.Lock()
        with _lock:
            self._subscriptions[_id] = (self._on_message if not callback else callback,payload)
        if not self._sub_thread:
            self._sub_thread = threading.Thread(target=self._sub_loop)
            self._sub_thread.start()
        return _id

    def unsubscribe(self, _id):
        if not self._conn:
            return None
        self._stop(_id)
        _lock = threading.Lock()
        with _lock:
            del self._subscriptions[_id]
            if len(self._subscriptions) == 0:
                self._sub_thread = None

    def close(self):
        if self._conn is None:
            return
        _lock = threading.Lock()
        with _lock:
            for id in self._subscriptions.keys():
                self._stop(id)
            self._subscriptions = {}

        if self._sub_thread:
            self._sub_thread.join()
            self._sub_thread = None
        try: # connection may be already reset by peer.
            self._conn_term()
            self._conn.close()
        except:
            pass
        self._conn = None