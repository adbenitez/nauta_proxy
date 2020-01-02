# -*- coding: utf-8 -*-
from datetime import datetime
import argparse
import json
import threading
import re
import selectors
import ssl
import socket
import socketserver
import sqlite3
import os


autocrypt_h = re.compile(rb'\r\nAutocrypt: (.|\n)+?=\r\n')
xmailer_h = re.compile(rb'\r\nX-Mailer: .+?\r\n')
subject_h = re.compile(rb'\r\nSubject: .+?\r\n')
header_part = re.compile(
    rb'\) BODY\[HEADER\.FIELDS\.NOT \(AUTOCRYPT X-MAILER RETURN-PATH DELIVERED-TO RECEIVED RECEIVED-SPF DKIM-SIGNATURE\)\] \{([0-9]+)\}')
text_part = re.compile(rb'\r\n\r\n BODY\[TEXT\] \{([0-9]+)\}\r\n')
msg_received = re.compile(rb'\* [0-9]+ FETCH \(UID [0-9]+ FLAGS \(.*?\) BODY')
msg_sent = re.compile(rb'250 2\.0\.0 Ok: queued as ')


def termux(cmd):
    resp = os.popen(cmd).read()
    if resp:
        return json.loads(resp)


class DBManager:
    def __init__(self):
        p = os.path.join(os.path.expanduser('~'), '.nauta_proxy.db')
        self.db = sqlite3.connect(p, check_same_thread=False)
        self.lock = threading.RLock()
        self.db.row_factory = sqlite3.Row
        self.execute('''CREATE TABLE IF NOT EXISTS stats
                        (key TEXT PRIMARY KEY,
                         value TEXT NOT NULL)''')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("stop", "0")')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("optimize", "1")')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("imap", "0")')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("smtp", "0")')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("imap_msgs", "0")')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("smtp_msgs", "0")')

    def reset(self):
        self.execute('REPLACE INTO stats VALUES ("imap", "0")')
        self.execute('REPLACE INTO stats VALUES ("smtp", "0")')
        self.execute('REPLACE INTO stats VALUES ("imap_msgs", "0")')
        self.execute('REPLACE INTO stats VALUES ("smtp_msgs", "0")')

    def execute(self, statement, args=()):
        with self.lock, self.db:
            return self.db.execute(statement, args)

    def get_stop(self):
        r = self.db.execute('SELECT value FROM stats WHERE key="stop"')
        return r.fetchone()[0] == "1"

    def set_stop(self, val):
        val = 1 if val else 0
        self.execute(
            'UPDATE stats SET value=? WHERE key="stop"', (val,))

    def get_optimize(self):
        r = self.db.execute('SELECT value FROM stats WHERE key="optimize"')
        return r.fetchone()[0] == "1"

    def set_optimize(self, val):
        val = 1 if val else 0
        self.execute(
            'UPDATE stats SET value=? WHERE key="optimize"', (val,))

    def get_imap(self):
        r = self.db.execute('SELECT value FROM stats WHERE key="imap"')
        return int(r.fetchone()[0])

    def set_imap(self, val):
        self.execute(
            'UPDATE stats SET value=? WHERE key="imap"', (val,))

    def get_smtp(self):
        r = self.db.execute('SELECT value FROM stats WHERE key="smtp"')
        return int(r.fetchone()[0])

    def set_smtp(self, val):
        self.execute(
            'UPDATE stats SET value=? WHERE key="smtp"', (val,))

    def get_imap_msgs(self):
        r = self.db.execute('SELECT value FROM stats WHERE key="imap_msgs"')
        return int(r.fetchone()[0])

    def set_imap_msgs(self, val):
        self.execute(
            'UPDATE stats SET value=? WHERE key="imap_msgs"', (val,))

    def get_smtp_msgs(self):
        r = self.db.execute('SELECT value FROM stats WHERE key="smtp_msgs"')
        return int(r.fetchone()[0])

    def set_smtp_msgs(self, val):
        self.execute(
            'UPDATE stats SET value=? WHERE key="smtp_msgs"', (val,))


class Proxy(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, port, real_host, real_port, use_ssl):
        self.real_host = real_host
        self.real_port = real_port
        self.use_ssl = use_ssl
        super().__init__(('', port), RequestHandler)


class RequestHandler(socketserver.BaseRequestHandler):

    def setup(self):
        if self.server.db.get_stop():
            print('Stopping {} Server...'.format(self.server.protocol))
            self.server.server_close()
            self.server.shutdown()

    def handle(self):
        real_server = (self.server.real_host, self.server.real_port)
        print('{} - {} CONNECTED. Forwarding to {}'.format(
            datetime.now(), self.client_address, real_server))

        with socket.create_connection(real_server) as sock:
            if self.server.use_ssl:
                context = ssl.create_default_context()
                sock = context.wrap_socket(
                    sock, server_hostname=real_server[0])

            forward = {self.request: sock, sock: self.request}

            sel = selectors.DefaultSelector()
            sel.register(self.request, selectors.EVENT_READ,
                         self.client_address)
            sel.register(sock, selectors.EVENT_READ, real_server)

            while True:
                events = sel.select()
                for key, mask in events:
                    print('\n{} - {} wrote:'.format(datetime.now(), key.data))
                    data = d = key.fileobj.recv(1024*4)

                    if self.server.protocol == 'IMAP' and key.data == real_server and msg_received.match(data):
                        end = b'OK Fetch completed.\r\n'
                    else:
                        end = b'\r\n'
                    while d and not d.endswith(end):
                        d = key.fileobj.recv(1024*4)
                        data += d

                    if self.server.protocol == 'SMTP':
                        if key.data == self.client_address and self.server.db.get_optimize():
                            data = autocrypt_h.sub(b'\r\n', data, count=1)
                            data = xmailer_h.sub(b'\r\n', data, count=1)
                            data = subject_h.sub(b'\r\n', data, count=1)

                        received = len(data)

                        if key.data == real_server:
                            if data.startswith(b'250-smtp.nauta.cu\r\n'):
                                data = data.replace(
                                    b'\r\n250-STARTTLS\r\n', b'\r\n')
                            elif msg_sent.match(data):
                                msgs = self.server.db.get_smtp_msgs()
                                self.server.db.set_smtp_msgs(msgs+1)

                        total = self.server.db.get_smtp() + received
                        self.server.db.set_smtp(total)
                    else:
                        if key.data == self.client_address and self.server.db.get_optimize():
                            req = b' (FLAGS BODY.PEEK[])\r\n'
                            sub = b' (FLAGS BODY.PEEK[HEADER.FIELDS.NOT (AUTOCRYPT X-MAILER RETURN-PATH DELIVERED-TO RECEIVED RECEIVED-SPF DKIM-SIGNATURE)] BODY.PEEK[TEXT])\r\n'
                            if data.endswith(req) and data.find(b' UID FETCH ') != -1:
                                data = data[:-len(req)] + sub

                        received = len(data)

                        if key.data == real_server:
                            if data.startswith(b'* OK [CAPABILITY '):
                                data = data.replace(b'STARTTLS', b'')
                            elif msg_received.match(data):
                                if self.server.db.get_optimize():
                                    try:
                                        m1 = header_part.search(data)
                                        size = int(m1[1])
                                        m2 = text_part.search(data)
                                        size += int(m2[1])
                                        data = data[:m2.start()] + \
                                            b'\r\n\r\n' + data[m2.end():]
                                        data = data[:m1.start()] + \
                                            b') BODY[] {%i}' % (
                                                size,) + data[m1.end():]
                                    except Exception as ex:
                                        print("ERROR:", ex)
                                msgs = self.server.db.get_imap_msgs()
                                self.server.db.set_imap_msgs(msgs+1)

                        total = self.server.db.get_imap() + received
                        self.server.db.set_imap(total)

                    print(data)
                    print('{} - {:,} Bytes'.format(
                        self.server.protocol, received))
                    print('Total: {:,} Bytes'.format(total))

                    if data:
                        forward[key.fileobj].sendall(data)
                    else:
                        print('\n{} - CLOSING CONNECTION.\n\n'.format(
                            self.server.protocol))
                        forward[key.fileobj].close()
                        key.fileobj.close()
                        return


def start_proxy(proxy_port, host, port, protocol, db):
    print('{} Proxy Started'.format(protocol))
    try:
        proxy = Proxy(proxy_port, host, port, False)
        proxy.protocol = protocol
        proxy.db = db
        proxy.serve_forever()
    finally:
        proxy.server_close()


def is_running():
    try:
        with socket.create_connection(('localhost', 8082)):
            pass
        with socket.create_connection(('localhost', 8081)):
            pass
        return True
    except:
        return False


def main():
    p = argparse.ArgumentParser(description='Simple Python Proxy')
    p.add_argument("--mode", help="set proxy mode: 1 (optimize),  0 (normal) or t (toggle)",
                   choices=['1', '0', 't'])
    p.add_argument("-r", help="reset db", action="store_true")
    p.add_argument("--stats", help="print the stats", action="store_true")
    p.add_argument("--stop", help="stop proxy", action="store_true")
    p.add_argument("--options", help="show options (needs termux)",
                   action="store_true")
    args = p.parse_args()
    db = DBManager()

    if args.options:
        running = is_running()
        options = ['Toogle Mode', 'Reset Stats',
                   'Stop Proxy' if running else 'Start Proxy']
        res = termux('termux-dialog sheet -v "{}"'.format(','.join(options)))
        if res['code'] == 0:
            if res['index'] == 0:
                args.mode = 't'
            elif res['index'] == 1:
                args.r = True
            elif res['index'] == 2:
                if running:
                    args.stop = True
        else:
            args.options = False

    if args.r:
        db.reset()
    elif args.stop:
        db.set_stop(True)
        with socket.create_connection(('localhost', 8082)):
            pass
        with socket.create_connection(('localhost', 8081)):
            pass
    elif args.stats:
        state = 'Running' if is_running() else 'Stopped'
        mode = 'Lite' if db.get_optimize() else 'Normal'
        print('State: {} ({})'.format(state, mode))
        print('IMAP: {:,} Bytes'.format(db.get_imap()))
        print('SMTP: {:,} Bytes'.format(db.get_smtp()))
        print('Received: {:,} msgs'.format(db.get_imap_msgs()))
        print('Sent: {:,} msgs\n'.format(db.get_smtp_msgs()))
    elif args.mode is not None:
        if args.mode == 't':
            db.set_optimize(not db.get_optimize())
        else:
            db.set_optimize(args.mode == '1')
    else:
        db.set_stop(False)
        threading.Thread(target=start_proxy, args=(
            8081, 'smtp.nauta.cu', 25, 'SMTP', db)).start()
        threading.Thread(target=start_proxy, args=(
            8082, 'imap.nauta.cu', 143, 'IMAP', db)).start()

    if args.options:
        os.system('bash ~/.shortcuts/Nauta-Proxy -r')
