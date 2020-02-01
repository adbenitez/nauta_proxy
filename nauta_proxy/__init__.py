# -*- coding: utf-8 -*-
import argparse
import imaplib
import json
import logging
import logging.handlers
import os
import re
import selectors
import socket
import socketserver
import threading
import time
import sqlite3


__author__ = 'Asiel Díaz Benítez'
__version__ = '0.6.0'


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
        self.execute('INSERT OR IGNORE INTO stats VALUES ("db_version", "1")')
        self.execute(
            'INSERT OR IGNORE INTO stats VALUES ("ignored_headers", "AUTOCRYPT RETURN-PATH RECEIVED RECEIVED-SPF DKIM-SIGNATURE")')
        self.execute(
            'INSERT OR IGNORE INTO stats VALUES ("serverstats", "0 0")')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("credentials", "")')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("savelog", "0")')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("stop", "0")')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("optimize", "1")')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("imap", "0")')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("smtp", "0")')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("imap_msgs", "0")')
        self.execute('INSERT OR IGNORE INTO stats VALUES ("smtp_msgs", "0")')

        h = self.get_ignoredheaders().encode()
        self.header_part = re.compile(
            rb'\) BODY\[HEADER\.FIELDS\.NOT \(' + h + rb'\)\] \{([0-9]+)\}')
        self.fetch_sub = b' (FLAGS BODY.PEEK[HEADER.FIELDS.NOT (' + \
            h + b')] BODY.PEEK[TEXT])\r\n'

    def reset(self):
        self.execute('REPLACE INTO stats VALUES ("imap", "0")')
        self.execute('REPLACE INTO stats VALUES ("smtp", "0")')
        self.execute('REPLACE INTO stats VALUES ("imap_msgs", "0")')
        self.execute('REPLACE INTO stats VALUES ("smtp_msgs", "0")')

    def execute(self, statement, args=()):
        with self.lock, self.db:
            return self.db.execute(statement, args)

    def get_ignoredheaders(self):
        r = self.db.execute(
            'SELECT value FROM stats WHERE key="ignored_headers"')
        return r.fetchone()[0]

    def set_ignoredheaders(self, val):
        self.execute(
            'UPDATE stats SET value=? WHERE key="ignored_headers"', (val,))

    def get_serverstats(self):
        r = self.db.execute('SELECT value FROM stats WHERE key="serverstats"')
        return tuple(int(i) for i in r.fetchone()[0].split())

    def set_serverstats(self, val):
        val = '{} {}'.format(*val)
        self.execute(
            'UPDATE stats SET value=? WHERE key="serverstats"', (val,))

    def get_credentials(self):
        r = self.db.execute('SELECT value FROM stats WHERE key="credentials"')
        return r.fetchone()[0].split(' ', maxsplit=1)

    def set_credentials(self, val):
        val = ' '.join(map(lambda v: v.decode(), val))
        self.execute(
            'UPDATE stats SET value=? WHERE key="credentials"', (val,))

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

    def __init__(self, port, handler, db):
        self.db = db
        self.loggerC, self.loggerF = self._init_loggers(handler.protocol)

        super().__init__(('', port), handler)

    def exception(self, ex):
        self.loggerC.exception(ex)
        if self.db.get_savelog():
            self.loggerF.exception(ex)

    def log(self, msg):
        self.loggerC.debug(msg)
        if self.db.get_savelog():
            self.loggerF.debug(msg)

    def debug(self, msg):
        if self.db.get_savelog():
            self.loggerC.debug(msg)
            self.loggerF.debug(msg)

    def _init_loggers(self, protocol):
        loggerC = logging.Logger(protocol)
        loggerC.parent = None
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(message)s')
        chandler = logging.StreamHandler()
        chandler.setLevel(logging.DEBUG)
        chandler.setFormatter(formatter)
        loggerC.addHandler(chandler)

        loggerF = logging.Logger(protocol)
        loggerF.parent = None
        formatter = logging.Formatter(
            '%(asctime)s - %(message)s')
        log_path = os.path.join(os.path.expanduser('~'), protocol+'.log')
        fhandler = logging.handlers.RotatingFileHandler(
            log_path, backupCount=2, maxBytes=10000000)
        fhandler.setLevel(logging.DEBUG)
        fhandler.setFormatter(formatter)
        loggerF.addHandler(fhandler)

        return (loggerC, loggerF)


class RequestHandler(socketserver.BaseRequestHandler):

    def setup(self):
        if self.server.db.get_stop():
            self.server.log('Stopping Server...')
            self.server.server_close()
            self.server.shutdown()

    def handle(self):
        self.server.log('{} CONNECTED'.format(self.client_address))
        sel = selectors.DefaultSelector()
        sel.register(self.request, selectors.EVENT_READ, self.client_address)
        try:
            with socket.create_connection(self.real_server) as sock:
                forward = {self.request: sock, sock: self.request}
                sel.register(sock, selectors.EVENT_READ, self.real_server)
                self._handle(self.server.db, self.server.log, sel, forward)
        except Exception as ex:
            self.server.exception(ex)
            time.sleep(30)
        finally:
            self.server.log('CLOSING CONNECTION.')

    def _handle(self, db, log, sel, forward):
        pass


class SmtpHandler(RequestHandler):
    protocol = 'SMTP'
    real_server = ('smtp.nauta.cu', 25)

    autocrypt_h = re.compile(rb'\r\nAutocrypt: (.|\n)+?=\r\n')
    xmailer_h = re.compile(rb'\r\nX-Mailer: .+?\r\n')
    subject_h = re.compile(rb'\r\nSubject: .+?\r\n')
    references_h = re.compile(rb'\r\nReferences: (.|\n)+?\r\n(?!\t)')
    inreplyto_h = re.compile(rb'\r\nIn-Reply-To: .+?\r\n')
    # messageid_h = re.compile(rb'\r\nMessage-ID: .+?\r\n')
    to_h = re.compile(rb'\r\nTo: ((.|\n)+?\r\n)(?!\t)')
    contenttype_h = re.compile(rb'Content-Type: .+?\r\n')
    addr_field = re.compile(rb'[^,]*?<([^<>]+)>')
    msg_sent = re.compile(rb'250 2\.0\.0 Ok: queued as ')

    def _handle(self, db, log, sel, forward):
        while True:
            events = sel.select()
            for key, mask in events:
                data = d = key.fileobj.recv(1024*4)
                if key.data == self.real_server:
                    while d and not data.endswith(b'\r\n'):
                        d = key.fileobj.recv(1024*4)
                        data += d

                    if data.startswith(b'250-smtp.nauta.cu\r\n'):
                        data = data.replace(
                            b'\r\n250-STARTTLS\r\n', b'\r\n')
                    elif self.msg_sent.match(data):
                        msgs = db.get_smtp_msgs()
                        db.set_smtp_msgs(msgs+1)
                else:  # key.data == self.client_address
                    if db.get_optimize():
                        if self.contenttype_h.search(data):
                            end = b'\r\n.\r\n'
                            while d and not data.endswith(end) and len(data) < 1024*4:
                                d = key.fileobj.recv(1024*4)
                                data += d
                        data = self.autocrypt_h.sub(b'\r\n', data, count=1)
                        data = self.xmailer_h.sub(b'\r\n', data, count=1)
                        data = self.subject_h.sub(b'\r\n', data, count=1)
                        data = self.references_h.sub(b'\r\n', data, count=1)
                        data = self.inreplyto_h.sub(b'\r\n', data, count=1)
                        # data = self.messageid_h.sub(b'\r\n', data, count=1)

                        m = self.to_h.search(data)
                        if m:
                            to = b'\r\nTo: '
                            to += b', \r\n\t'.join(self.addr_field.sub(
                                rb'\1', m[1]).split(b','))
                            data = data[:m.start()] + to + \
                                data[m.end():]

                    if data == b'QUIT\r\n':
                        self.request.sendall(b'2.0.0 Bye\r\n')
                        self.request.close()

                received = len(data)
                total = db.get_smtp() + received
                db.set_smtp(total)

                received = '{:,} Bytes'.format(received)
                total = '{} Total: {:,} Bytes'.format(
                    self.protocol, total)
                if db.get_savelog():
                    log('{} wrote:\n{}\n{}\n{}'.format(
                        key.data, data, received, total))
                else:
                    log('{} wrote:\n{}\n{}'.format(
                        key.data, received, total))

                forward[key.fileobj].sendall(data)
                if not data:
                    self.request.close()
                    return


class ImapHandler(RequestHandler):
    protocol = 'IMAP'
    real_server = ('imap.nauta.cu', 143)

    text_part = re.compile(rb'\r\n\r\n BODY\[TEXT\] \{([0-9]+)\}\r\n')
    msg_received = re.compile(
        rb'\* [0-9]+ FETCH \(UID [0-9]+ FLAGS \(.*?\) BODY')
    login_cmd = re.compile(rb'[a-zA-Z0-9]+ LOGIN "(.+?)" "(.+?)"\r\n')

    def _handle(self, db, log, sel, forward):
        while True:
            events = sel.select()
            for key, mask in events:
                # self.server.loggerC.debug('{} writing...'.format(key.data))
                data = d = key.fileobj.recv(1024*4)
                if key.data == self.real_server:
                    if self.msg_received.match(data):
                        end = b'OK Fetch completed.\r\n'
                    else:
                        end = b'\r\n'
                    while d and not data.endswith(end):
                        d = key.fileobj.recv(1024*4)
                        data += d

                    if data.startswith(b'* OK [CAPABILITY '):
                        data = data.replace(b'STARTTLS', b'')
                    elif self.msg_received.match(data):
                        if db.get_optimize():
                            try:
                                m1 = db.header_part.search(data)
                                size = int(m1[1])
                                m2 = self.text_part.search(data)
                                size += int(m2[1])
                                data = data[:m2.start()] + \
                                    b'\r\n\r\n' + data[m2.end():]
                                data = data[:m1.start()] + \
                                    b') BODY[] {%i}' % (
                                        size,) + data[m1.end():]
                            except Exception as ex:
                                self.server.exception(ex)
                        msgs = db.get_imap_msgs()
                        db.set_imap_msgs(msgs+1)
                else:  # key.data == self.client_address
                    while d and not data.endswith(b'\r\n'):
                        d = key.fileobj.recv(1024*4)
                        data += d

                    if db.get_optimize():
                        req = b' (FLAGS BODY.PEEK[])\r\n'
                        if data.endswith(req) and data.find(b' UID FETCH ') != -1:
                            data = data[:-len(req)] + db.fetch_sub

                    m = self.login_cmd.match(data)
                    if m:
                        db.set_credentials(m.group(1, 2))

                received = len(data)
                total = db.get_imap() + received
                db.set_imap(total)

                received = '{:,} Bytes'.format(received)
                total = '{} Total: {:,} Bytes'.format(
                    self.protocol, total)
                if db.get_savelog():
                    log('{} wrote:\n{}\n{}\n{}'.format(
                        key.data, data, received, total))
                else:
                    log('{} wrote:\n{}\n{}'.format(
                        key.data, received, total))

                forward[key.fileobj].sendall(data)
                if not data:
                    self.request.close()
                    return


def start_proxy(proxy_port, handler, db):
    proxy = Proxy(proxy_port, handler, db)
    proxy.log('Proxy Started')
    try:
        proxy.serve_forever()
    finally:
        proxy.server_close()


def is_running():
    try:
        with socket.create_connection(('127.0.0.1', 8081)):
            pass
        return True
    except:
        return False


def convert_bytes(amount):
    if amount < 1024:
        amount = '{}B'.format(amount)
    elif amount < 1024**2:
        amount = '{:.3f}KB'.format(amount/1024)
    else:
        amount = '{:.3f}MB'.format(amount/1024**2)
    return amount


def get_stats(db):
    state = 'En Ejecución' if is_running() else 'Detenido'
    mode = 'Lite' if db.get_optimize() else 'Normal'
    text = 'Estado: {} ({})\n'.format(state, mode)
    text += 'Recibido: {:,} / {}\n'.format(
        db.get_imap_msgs(), convert_bytes(db.get_imap()))
    text += 'Enviado: {:,} / {}\n'.format(
        db.get_smtp_msgs(), convert_bytes(db.get_smtp()))
    serv_msgs, serv_bytes = db.get_serverstats()
    text += 'Servidor: {:,} / {}\n'.format(
        serv_msgs, convert_bytes(serv_bytes))
    return text


def empty_dc(db, folder):
    c = db.get_credentials()
    if c:
        with imaplib.IMAP4('127.0.0.1', 8082) as imap:
            imap.login(*c)
            resp = imap.select(folder)
            assert resp[0] == 'OK', resp[1]
            imap.store('1:*', '+FLAGS.SILENT', r'\Deleted')
            imap.close()
            quota = imap.getquotaroot('INBOX')
        quota = quota[1][1][0].split(b'(')[1][:-1].split()
        db.set_serverstats((int(quota[-2]), int(quota[1])))


def update_serverstats(db):
    c = db.get_credentials()
    if c:
        with imaplib.IMAP4('127.0.0.1', 8082) as imap:
            imap.login(*c)
            quota = imap.getquotaroot('INBOX')
        quota = quota[1][1][0].split(b'(')[1][:-1].split()
        db.set_serverstats((int(quota[-2]), int(quota[1])))


def main():
    p = argparse.ArgumentParser(description='Simple Python Proxy')
    p.add_argument("-v", "--version", help="show program's version number",
                   action="version", version=__version__)
    p.add_argument("--mode", help="set proxy mode: 1 (optimize),  0 (normal)",
                   choices=['1', '0'])
    p.add_argument("--log", help="1 (save logs) or 0 (don't save logs)",
                   choices=['1', '0'])
    p.add_argument("--serverstats", help="update server stats",
                   action="store_true")
    p.add_argument("--empty", help="empty INBOX/DeltaChat folder or the given folder",
                   const="INBOX/DeltaChat", nargs='?')
    p.add_argument("--notheaders", help="set headers to ignore, or print the current ignored headers if no argument is given",
                   const="", nargs='?')
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
        options = [
            'Detener Proxy',
            'Resetear Stats',
            'Vaciar Carpeta DeltaChat',
            'Modo Normal' if optimize else 'Modo Lite',
            'Mostrar Stats']
        res = termux('termux-dialog sheet -v "{}"'.format(','.join(options)))
        if res['code'] == 0:
            if res['index'] == 0:
                args.stop = True
            elif res['index'] == 1:
                args.r = True
            elif res['index'] == 2:
                args.empty = 'INBOX/DeltaChat'
            elif res['index'] == 3:
                args.mode = '0' if optimize else '1'
            elif res['index'] == 4:
                update_serverstats(db)
                termux('termux-dialog confirm -t "{}" -i "{}"'.format(
                    'Nauta Proxy {}'.format(__version__), get_stats(db)))
        else:
            args.options = False

    if args.r:
        db.reset()
    elif args.n:
        os.system(cmd)
    elif args.stop:
        db.set_stop(True)
        with socket.create_connection(('127.0.0.1', 8082)):
            pass
        with socket.create_connection(('127.0.0.1', 8081)):
            pass
    elif args.stats:
        print(get_stats(db))
    elif args.serverstats:
        update_serverstats(db)
    elif args.empty:
        empty_dc(db, args.empty)
    elif args.notheaders is not None:
        if args.notheaders:
            args.notheaders = args.notheaders.upper()
            if args.notheaders.startswith('+'):
                args.notheaders = '{} {}'.format(
                    db.get_ignoredheaders(), args.notheaders[1:])
                db.set_ignoredheaders(args.notheaders)
        else:
            print(db.get_ignoredheaders())
    elif args.mode is not None:
        db.set_optimize(args.mode == '1')
    elif args.log is not None:
        db.set_savelog(args.log == '1')
    else:
        db.set_stop(False)
        threading.Thread(target=start_proxy, args=(
            8081, SmtpHandler, db)).start()
        threading.Thread(target=start_proxy, args=(
            8082, ImapHandler, db)).start()

    if args.options:
        os.system(cmd)
