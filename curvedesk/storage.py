"""Private per-user storage, bounded observations and consistent portable backups."""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import tempfile
import zipfile


def default_directory():
    override=os.environ.get('CURVEDESK_DATA_DIR')
    if override:return Path(override).expanduser().resolve()
    if os.name=='nt':return Path(os.environ.get('LOCALAPPDATA',Path.home()/'AppData'/'Local'))/'CurveDesk'
    return Path(os.environ.get('XDG_DATA_HOME',Path.home()/'.local'/'share'))/'curvedesk'


class Store:
    def __init__(self,directory=None):
        self.directory=Path(directory) if directory else default_directory()
        self.directory.mkdir(parents=True,exist_ok=True,mode=0o700)
        self.directory.chmod(0o700)
        self.path=self.directory/'curvedesk.db'
        with self.db() as c:
            c.executescript('''PRAGMA journal_mode=WAL;
            CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,payload TEXT);
            CREATE TABLE IF NOT EXISTS contracts(id TEXT PRIMARY KEY,payload TEXT);
            CREATE TABLE IF NOT EXISTS pairs(key TEXT PRIMARY KEY,payload TEXT);
            CREATE TABLE IF NOT EXISTS samples(id INTEGER PRIMARY KEY,key TEXT,observed REAL,payload TEXT);
            CREATE INDEX IF NOT EXISTS samples_key ON samples(key,id);
            CREATE TABLE IF NOT EXISTS bars(key TEXT,bucket INTEGER,open REAL,high REAL,low REAL,close REAL,samples INTEGER,PRIMARY KEY(key,bucket));
            CREATE INDEX IF NOT EXISTS bars_time ON bars(bucket);
            CREATE TABLE IF NOT EXISTS trades(id INTEGER PRIMARY KEY,key TEXT,status TEXT,payload TEXT);
            CREATE UNIQUE INDEX IF NOT EXISTS one_open_trade ON trades(key) WHERE status='OPEN';
            CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY,key TEXT,kind TEXT,created REAL,payload TEXT,ack INTEGER DEFAULT 0);
            ''')
        self.path.chmod(0o600)

    @contextlib.contextmanager
    def db(self):
        c=sqlite3.connect(self.path,timeout=10);c.row_factory=sqlite3.Row
        try:
            with c:yield c
        finally:c.close()

    def get(self,key,default=None):
        with self.db() as c:r=c.execute('SELECT payload FROM settings WHERE key=?',(key,)).fetchone()
        return json.loads(r[0]) if r else default

    def set(self,key,value):
        with self.db() as c:c.execute('INSERT OR REPLACE INTO settings VALUES(?,?)',(key,json.dumps(value,allow_nan=False)))

    def rows(self,table):
        queries={'contracts':'SELECT * FROM contracts','pairs':'SELECT * FROM pairs','trades':'SELECT * FROM trades'}
        if table not in queries:raise ValueError('Unknown collection')
        with self.db() as c:rows=c.execute(queries[table]).fetchall()
        return [json.loads(r['payload']) for r in rows]

    def backup(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot=Path(directory)/'snapshot.db'
            target=sqlite3.connect(snapshot)
            try:
                with self.db() as source:source.backup(target)
                # Portable snapshots must not retain WAL-mode file headers.
                target.execute('PRAGMA journal_mode=DELETE')
            finally:target.close()
            raw=snapshot.read_bytes()
        # Authentication is a separate local file; no credentials in SQLite.
        out=io.BytesIO()
        with zipfile.ZipFile(out,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('curvedesk.db',raw)
            z.writestr('manifest.json',json.dumps({'format':'curvedesk-v1','sha256':hashlib.sha256(raw).hexdigest(),'credentials':False}))
        return out.getvalue()

    def restore(self,raw):
        if len(raw)>100_000_000:raise ValueError('Backup exceeds 100 MB')
        try:
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                if set(z.namelist())!={'curvedesk.db','manifest.json'}:raise ValueError('Unexpected backup files')
                if sum(i.file_size for i in z.infolist())>100_000_000:raise ValueError('Expanded backup too large')
                manifest=json.loads(z.read('manifest.json'));database=z.read('curvedesk.db')
            if manifest.get('format')!='curvedesk-v1' or manifest.get('credentials') is not False or hashlib.sha256(database).hexdigest()!=manifest.get('sha256'):raise ValueError('Invalid backup manifest/checksum')
            incoming=sqlite3.connect(':memory:');incoming.deserialize(database)
            try:
                if incoming.execute('PRAGMA integrity_check').fetchone()[0]!='ok':raise ValueError('Corrupt backup database')
                objects=incoming.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'").fetchall()
                allowed={'settings','contracts','pairs','samples','bars','trades','alerts','samples_key','bars_time','one_open_trade'}
                if {r[1] for r in objects}!=allowed or any(r[0] not in ('table','index') for r in objects):raise ValueError('Unsupported backup schema')
                # Exact schema comparison prevents triggers/views or altered tables executing later.
                with self.db() as c:current={(r[0],r[1],r[2]) for r in c.execute("SELECT type,name,sql FROM sqlite_master WHERE name NOT LIKE 'sqlite_%'")}
                if set(objects)!=current:raise ValueError('Backup schema differs from this version')
                recovery=self.directory/'before-restore.zip';recovery.write_bytes(self.backup());recovery.chmod(0o600)
                with self.db() as dest:incoming.backup(dest)
            finally:incoming.close()
        except (zipfile.BadZipFile,sqlite3.Error,KeyError,json.JSONDecodeError) as e:
            raise ValueError('Invalid CurveDesk backup') from e
