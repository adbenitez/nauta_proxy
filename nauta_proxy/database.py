# -*- coding: utf-8 -*-
import os
import re
import sqlite3
import threading


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
        r = self.db.execute(
            'SELECT value FROM stats WHERE key="credentials"').fetchone()
        return r and r[0].split(' ', maxsplit=1)

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
        r = self.db.execute(
            'SELECT value FROM stats WHERE key="optimize"').fetchone()
        return int(r[0])

    def set_optimize(self, val):
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
