"""Loopback-only desktop HTTP interface with same-origin mutation protection."""
import base64
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse
from .desk import Desk

STATIC=Path(getattr(sys,'_MEIPASS',Path(__file__).resolve().parents[1]))/'static'


def create_server(desk,port=8876):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass

        def send(self,status,payload,mime='application/json',download=None):
            raw=json.dumps(payload,allow_nan=False).encode() if mime=='application/json' else payload
            self.send_response(status)
            for k,v in {'Content-Type':mime,'Content-Length':str(len(raw)),'Cache-Control':'no-store',
                        'X-Content-Type-Options':'nosniff','X-Frame-Options':'DENY','Referrer-Policy':'no-referrer',
                        'Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"}.items():self.send_header(k,v)
            if download:self.send_header('Content-Disposition','attachment; filename="'+download+'"')
            self.end_headers()
            try:self.wfile.write(raw)
            except (BrokenPipeError,ConnectionResetError):pass

        def guard(self,write=False):
            allowed={'127.0.0.1:'+str(self.server.server_port),'localhost:'+str(self.server.server_port)}
            origin=self.headers.get('Origin');host=self.headers.get('Host','')
            if host not in allowed or (origin and origin not in {'http://'+h for h in allowed}):
                self.send(403,{'error':'Local same-origin requests only'});return False
            if self.headers.get('Sec-Fetch-Site') in ('cross-site',):
                self.send(403,{'error':'Cross-site access refused'});return False
            if write and self.headers.get('X-CurveDesk')!='1':
                self.send(403,{'error':'Use the CurveDesk application to change data'});return False
            return True

        def do_GET(self):
            if not self.guard():return
            path=unquote(urlparse(self.path).path)
            try:
                if path=='/api/status':return self.send(200,desk.status())
                if path=='/api/settings':return self.send(200,desk.settings())
                if path=='/api/contracts':return self.send(200,desk.catalogue())
                if path=='/api/pairs':return self.send(200,{'pairs':desk.definitions()})
                if path=='/api/trades':return self.send(200,{'trades':desk.store.rows('trades'),'alerts':desk.alerts()})
                if path.startswith('/api/report/'):return self.send(200,desk.report(path.rsplit('/',1)[-1]))
                if path=='/api/backup':return self.send(200,desk.store.backup(),'application/zip','curvedesk-backup.zip')
                files={'/':'index.html','/app.js':'app.js','/style.css':'style.css','/icon.svg':'icon.svg'}
                if path in files:
                    name=files[path];mime={'html':'text/html; charset=utf-8','js':'text/javascript','css':'text/css','svg':'image/svg+xml'}[name.rsplit('.',1)[-1]]
                    return self.send(200,(STATIC/name).read_bytes(),mime)
                return self.send(404,{'error':'Not found; CurveDesk has no order endpoints'})
            except ValueError as e:self.send(400,{'error':str(e)[:500]})
            except Exception:self.send(500,{'error':'Request failed. Check data/storage; no synthetic data substituted.'})

        def do_POST(self):
            if not self.guard(True):return
            try:
                if self.headers.get('Content-Type','').split(';')[0]!='application/json':raise ValueError('JSON required')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=140_000_000:raise ValueError('Invalid request size')
                body=json.loads(self.rfile.read(length))
                if not isinstance(body,dict):raise ValueError('JSON object required')
                path=urlparse(self.path).path
                if path=='/api/connect':result=desk.dhan.save(body)
                elif path=='/api/test-dhan':result=desk.dhan.test()
                elif path=='/api/catalogue-refresh':result=desk.dhan.refresh_catalogue()
                elif path=='/api/settings':result=desk.save_settings(body)
                elif path=='/api/specification':result=desk.save_spec(body)
                elif path=='/api/pairs':result=desk.save_pair(body)
                elif path=='/api/pairs/delete':result=desk.delete_pair(str(body.get('key','')))
                elif path=='/api/scenario':result=desk.compare(body)
                elif path=='/api/trade':result=desk.trade(body)
                elif path=='/api/alerts/ack':
                    from .analytics import whole
                    with desk.store.db() as c:c.execute('UPDATE alerts SET ack=1 WHERE id=?',(whole(body.get('id'),'alert id',2**31),))
                    result={'acknowledged':True}
                elif path=='/api/history':result=desk.dhan.history(body)
                elif path=='/api/restore':
                    if body.get('confirmation')!='RESTORE CURVEDESK':raise ValueError('Type RESTORE CURVEDESK')
                    try:raw=base64.b64decode(body.get('backup',''),validate=True)
                    except Exception:raise ValueError('Invalid backup encoding') from None
                    with desk.lock:
                        desk.store.restore(raw)
                        with desk.dhan.lock:desk.dhan.revision+=1;desk.dhan.rows={}
                    result={'restored':True,'note':'Credentials were excluded. Previous database saved as before-restore.zip. Missing offline ticks remain gaps.'}
                else:return self.send(404,{'error':'Not found; no order execution exists'})
                return self.send(200,result)
            except (ValueError,KeyError,TypeError) as e:self.send(400,{'error':str(e)[:500]})
            except Exception:self.send(500,{'error':'Operation failed. Check connectivity and local storage.'})

    server=ThreadingHTTPServer(('127.0.0.1',port),Handler)
    server.daemon_threads=True
    return server


def main():
    desk=Desk();http=create_server(desk,int(os.environ.get('CURVEDESK_PORT','8876')));desk.start()
    print('CurveDesk: http://127.0.0.1:'+str(http.server_port)+' — research only',flush=True)
    try:http.serve_forever()
    except KeyboardInterrupt:pass
    finally:desk.stop.set();desk.dhan.stop.set();http.server_close()


if __name__=='__main__':main()
