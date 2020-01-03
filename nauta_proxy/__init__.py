# -*- coding: utf-8 -*-
import argparse
import json
import logging
import logging.handlers
import os
import re
import selectors
import socket
import socketserver
import threading
import sqlite3


__author__ = 'Asiel Díaz Benítez'
__version__ = '0.4.0'


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
        self.execute('INSERT OR IGNORE INTO stats VALUES ("savelog", "0")')
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

    def get_savelog(self):
        r = self.db.execute('SELECT value FROM stats WHERE key="savelog"')
        return r.fetchone()[0] == "1"

    def set_savelog(self, val):
        val = 1 if val else 0
        self.execute(
            'UPDATE stats SET value=? WHERE key="savelog"', (val,))

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

    def __init__(self, port, real_host, real_port):
        self.real_host = real_host
        self.real_port = real_port
        super().__init__(('', port), RequestHandler)


class RequestHandler(socketserver.BaseRequestHandler):

    def setup(self):
        if self.server.db.get_stop():
            self.server.logger.debug('Stopping Server...')
            self.server.server_close()
            self.server.shutdown()

    def handle(self):
        try:
            self._handle()
        except Exception as ex:
            self.server.logger.exception(ex)
        finally:
            self.server.logger.debug('CLOSING CONNECTION.')
            self.request.close()

    def _handle(self):
        real_server = (self.server.real_host, self.server.real_port)
        self.server.logger.debug('%s CONNECTED', self.client_address)

        with socket.create_connection(real_server) as sock:
            forward = {self.request: sock, sock: self.request}

            sel = selectors.DefaultSelector()
            sel.register(self.request, selectors.EVENT_READ,
                         self.client_address)
            sel.register(sock, selectors.EVENT_READ, real_server)

            while True:
                events = sel.select()
                for key, mask in events:
                    self.server.logger.debug('%s writing...', key.data)
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
                                        self.server.logger.exception(ex)
                                msgs = self.server.db.get_imap_msgs()
                                self.server.db.set_imap_msgs(msgs+1)

                        total = self.server.db.get_imap() + received
                        self.server.db.set_imap(total)

                    received = '{:,} Bytes'.format(received)
                    total = 'Total: {:,} Bytes'.format(total)
                    self.server.logger.debug('%s wrote:\n%s\n%s\n%s',
                                             key.data, data, received, total)

                    if data:
                        forward[key.fileobj].sendall(data)
                    else:
                        return


def init_logger(protocol, save):
    logger = logging.Logger(protocol)
    logger.parent = None

    formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(message)s')
    chandler = logging.StreamHandler()
    chandler.setLevel(logging.DEBUG)
    chandler.setFormatter(formatter)
    logger.addHandler(chandler)

    if save:
        formatter = logging.Formatter(
            '%(asctime)s - %(message)s')
        log_path = os.path.join(os.path.expanduser('~'), protocol+'.log')
        fhandler = logging.handlers.RotatingFileHandler(
            log_path, backupCount=2, maxBytes=10000000)
        fhandler.setLevel(logging.DEBUG)
        fhandler.setFormatter(formatter)
        logger.addHandler(fhandler)

    return logger


def start_proxy(proxy_port, host, port, protocol, db):
    proxy = Proxy(proxy_port, host, port, False)
    proxy.protocol = protocol
    proxy.db = db
    proxy.logger = init_logger(protocol, db.get_savelog())
    proxy.logger.debug('Proxy Started')
    try:
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
    p.add_argument("-v", "--version", help="show program's version number",
                   action="version", version=__version__)
    p.add_argument("--mode", help="set proxy mode: 1 (optimize),  0 (normal)",
                   choices=['1', '0'])
    p.add_argument("--log", help="1 (save logs) or 0 (don't save logs)",
                   choices=['1', '0'])
    p.add_argument("-r", help="reset db", action="store_true")
    p.add_argument("-n", help="show notification", action="store_true")
    p.add_argument("--stats", help="print the stats", action="store_true")
    p.add_argument("--stop", help="stop proxy", action="store_true")
    p.add_argument("--options", help="show options (needs termux)",
                   action="store_true")
    args = p.parse_args()
    db = DBManager()
    cmd = 'bash ~/.shortcuts/Nauta-Proxy -r'

    if args.options:
        optimize = db.get_optimize()
        running = is_running()
        options = ['Modo Normal' if optimize else 'Modo Lite',
                   'Mostrar Stats',
                   'Resetear Stats',
                   'Detener Proxy' if running else 'Iniciar Proxy']
        res = termux('termux-dialog sheet -v "{}"'.format(','.join(options)))
        if res['code'] == 0:
            if res['index'] == 0:
                args.mode = '0' if optimize else '1'
            elif res['index'] == 1:
                state = 'En Ejecución' if is_running() else 'Detenido'
                mode = 'Lite' if db.get_optimize() else 'Normal'
                text = 'Estado: {} ({})\n'.format(state, mode)
                text += 'Recibido: {:,}msg / {:,}B\n'.format(
                    db.get_imap_msgs(), db.get_imap())
                text += 'Enviado: {:,}msg / {:,}B\n'.format(
                    db.get_smtp_msgs(), db.get_smtp())
                title = 'Nauta Proxy {}'.format(__version__)
                termux('termux-dialog confirm -t "{}" -i "{}"'.format(
                    title, text))
            elif res['index'] == 2:
                args.r = True
            elif res['index'] == 3:
                if running:
                    args.stop = True
        else:
            args.options = False

    if args.r:
        db.reset()
    elif args.n:
        os.system(cmd)
    elif args.stop:
        db.set_stop(True)
        with socket.create_connection(('localhost', 8082)):
            pass
        with socket.create_connection(('localhost', 8081)):
            pass
    elif args.stats:
        state = 'En Ejecución' if is_running() else 'Detenido'
        mode = 'Lite' if db.get_optimize() else 'Normal'
        print('Estado: {} ({})'.format(state, mode))
        print('Recibido: {:,} / {:,}B'.format(
            db.get_imap_msgs(), db.get_imap()))
        print(
            'Enviado: {:,} / {:,}B'.format(db.get_smtp_msgs(), db.get_smtp()))
    elif args.mode is not None:
        db.set_optimize(args.mode == '1')
    elif args.log is not None:
        db.set_savelog(args.log == '1')
    else:
        db.set_stop(False)
        threading.Thread(target=start_proxy, args=(
            8081, 'smtp.nauta.cu', 25, 'SMTP', db)).start()
        threading.Thread(target=start_proxy, args=(
            8082, 'imap.nauta.cu', 143, 'IMAP', db)).start()

    if args.options:
        os.system(cmd)
