# -*- coding: utf-8 -*-
import logging
import logging.handlers
import os
import re
import socket
import socketserver
import selectors
import time


IMAP_SERVER = ('imap.nauta.cu', 143)
SMTP_SERVER = ('smtp.nauta.cu', 25)


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
    real_server = SMTP_SERVER

    autocrypt_h = re.compile(rb'\r\nAutocrypt: (.|\n)+?\r\n(?!\t)')
    xmailer_h = re.compile(rb'\r\nX-Mailer: (.|\n)+?\r\n(?!\t)')
    subject_h = re.compile(rb'\r\nSubject: (.|\n)+?\r\n(?!\t)')
    references_h = re.compile(rb'\r\nReferences: (.|\n)+?\r\n(?!\t)')
    inreplyto_h = re.compile(rb'\r\nIn-Reply-To: (.|\n)+?\r\n(?!\t)')
    # messageid_h = re.compile(rb'\r\nMessage-ID: (.|\n)+?\r\n(?!\t)')
    contenttype_h = re.compile(rb'Content-Type: (.|\n)+?\r\n(?!\t)')
    to_h = re.compile(rb'\r\nTo: ((.|\n)+?\r\n)(?!\t)')
    addr_field = re.compile(rb'[^,]*?<([^<>]+)>')
    msg_sent = re.compile(rb'250 2\.0\.0 Ok: queued as ')

    def _handle(self, db, log, sel, forward):
        while True:
            events = sel.select()
            for key, mask in events:
                data = d = key.fileobj.recv(1024)
                if key.data == self.real_server:
                    while d and not data.endswith(b'\r\n'):
                        d = key.fileobj.recv(1024)
                        data += d

                    if data.startswith(b'250-smtp.nauta.cu\r\n'):
                        data = data.replace(
                            b'\r\n250-STARTTLS\r\n', b'\r\n')
                    elif self.msg_sent.match(data):
                        msgs = db.get_smtp_msgs()
                        db.set_smtp_msgs(msgs+1)
                else:  # key.data == self.client_address
                    if db.get_optimize():
                        if self.contenttype_h.search(data):  # Outgoing message
                            end = b'\r\n.\r\n'
                            while d and not data.endswith(end) and len(data) < 1024*4:
                                d = key.fileobj.recv(1024)
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
    real_server = IMAP_SERVER

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
                        while d and not data.endswith(end):
                            d = key.fileobj.recv(1024*4)
                            data += d
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
                    else:
                        while d and not data.endswith(b'\r\n'):
                            d = key.fileobj.recv(1024*4)
                            data += d
                        if data.startswith(b'* OK [CAPABILITY '):
                            data = data.replace(b'STARTTLS', b'')
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
