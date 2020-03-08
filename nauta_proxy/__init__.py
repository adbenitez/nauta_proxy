# -*- coding: utf-8 -*-
import argparse
import imaplib
import json
import os
import socket
import subprocess
import threading

from .database import DBManager
from .proxy import Proxy, SmtpHandler, ImapHandler, IMAP_SERVER


__author__ = 'Asiel Díaz Benítez'
__version__ = '0.9.0'


def termux(cmd):
    resp = os.popen(cmd).read()
    if resp:
        return json.loads(resp)


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
        with imaplib.IMAP4(*IMAP_SERVER) as imap:
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
        with imaplib.IMAP4(*IMAP_SERVER) as imap:
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
    p.add_argument("--upgrade", help="check for updates of nauta proxy",
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
            'Vaciar Carpeta...',
            'Resetear Stats',
            'Modo Normal' if optimize else 'Modo Lite',
            'Mostrar Stats',
            'Actualizar App']
        res = termux('termux-dialog sheet -v "{}"'.format(','.join(options)))
        if res['code'] == 0:
            if res['index'] == 0:
                args.stop = True
            elif res['index'] == 1:
                options = [
                    'INBOX',
                    'INBOX/DeltaChat',
                    'DeltaChat',
                    'Trash',
                    'Sent',
                    'Drafts']
                res = termux(
                    'termux-dialog sheet -v "{}"'.format(','.join(options)))
                if res['code'] == 0:
                    args.empty = options[res['index']]
            elif res['index'] == 2:
                args.r = True
            elif res['index'] == 3:
                args.mode = '0' if optimize else '1'
            elif res['index'] == 4:
                update_serverstats(db)
                termux('termux-dialog confirm -t "{}" -i "{}"'.format(
                    'Nauta Proxy {}'.format(__version__), get_stats(db)))
            elif res['index'] == 5:
                args.upgrade = True
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
    elif args.upgrade:
        subprocess.run(('pip', 'install', '-U', 'nauta-proxy'))
    else:
        db.set_stop(False)
        threading.Thread(target=start_proxy, args=(
            8081, SmtpHandler, db)).start()
        threading.Thread(target=start_proxy, args=(
            8082, ImapHandler, db)).start()

    if args.options:
        os.system(cmd)
