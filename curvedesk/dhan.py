"""Dhan data only: no order, position-management or execution APIs exist here."""
import csv
import io
import json
import logging
import math
import os
import struct
import threading
import time
from datetime import datetime
from urllib.parse import urlencode
import urllib.request
import urllib.error
from zoneinfo import ZoneInfo
from .analytics import finite

IST=ZoneInfo('Asia/Kolkata')
MASTER='https://images.dhan.co/api-data/api-scrip-master-detailed.csv'


def parse_master(text,today=None):
    today=today or datetime.now(IST).date().isoformat();rows=[];seen=set()
    for r in csv.DictReader(io.StringIO(text.lstrip('\ufeff'))):
        field=lambda *keys:next((str(r[k]).strip() for k in keys if r.get(k)),'')
        if field('EXCH_ID','SEM_EXM_EXCH_ID')!='MCX' or field('INSTRUMENT','SEM_INSTRUMENT_NAME')!='FUTCOM':continue
        sid=field('SECURITY_ID','SEM_SMST_SECURITY_ID');symbol=field('SYMBOL_NAME','SM_SYMBOL_NAME');expiry=field('SM_EXPIRY_DATE','SEM_EXPIRY_DATE')[:10]
        try:datetime.strptime(expiry,'%Y-%m-%d')
        except ValueError:continue
        lot=finite(field('LOT_SIZE','SEM_LOT_UNITS'));tick=finite(field('TICK_SIZE','SEM_TICK_SIZE'))
        if not sid.isdigit() or sid in seen or not symbol or expiry<today or not lot or lot<=0:continue
        rows.append({'id':sid,'symbol':symbol,'expiry':expiry,'label':f'{symbol} · {expiry}',
                     'lot_units':lot,'tick':tick,'source':'Dhan instrument master'})
        seen.add(sid)
    if not rows:raise ValueError('No unexpired MCX futures found; previous catalogue retained')
    return sorted(rows,key=lambda r:(r['symbol'],r['expiry']))


def decode(raw,received=None):
    now=time.time() if received is None else received;offset=0;out=[]
    while offset<len(raw):
        if len(raw)-offset<8:raise ValueError('Truncated Dhan header')
        code,size,segment,sid=struct.unpack_from('<BHBI',raw,offset)
        if size<8 or offset+size>len(raw):raise ValueError('Invalid Dhan packet length')
        p=raw[offset:offset+size];offset+=size
        if code==50:
            reason=struct.unpack_from('<H',p,8)[0] if size>=10 else 0
            raise ValueError('Dhan feed disconnected: code '+str(reason))
        if code!=8 or segment!=5:continue
        if size!=162:raise ValueError('Dhan full-packet schema changed')
        last=struct.unpack_from('<f',p,8)[0];ltt=struct.unpack_from('<I',p,14)[0]
        volume=struct.unpack_from('<I',p,22)[0];oi=struct.unpack_from('<I',p,34)[0]
        levels=[struct.unpack_from('<IIHHff',p,62+i*20) for i in range(5)]
        bids=[{'price':x[4],'quantity':x[0]} for x in levels if math.isfinite(x[4]) and x[4]>0 and x[0]>0]
        asks=[{'price':x[5],'quantity':x[1]} for x in levels if math.isfinite(x[5]) and x[5]>0 and x[1]>0]
        if not math.isfinite(last) or last<=0:continue
        out.append((str(sid),{'last':last,'trade_time':ltt,'volume':volume,'oi':oi,'received_at':now,
                             'bid':max((x['price'] for x in bids),default=0),'ask':min((x['price'] for x in asks),default=0),
                             'depth':{'buy':sorted(bids,key=lambda x:-x['price']),'sell':sorted(asks,key=lambda x:x['price'])}}))
    return out


class Dhan:
    def __init__(self,store):
        self.store=store;self.secret_path=store.directory/'dhan.json';self.lock=threading.RLock();self.rows={}
        self.state='NOT_CONFIGURED';self.error=None;self.last_packet=None;self.verified=False;self.stop=threading.Event();self.revision=0
        self.catalogue_error=None;self.catalogue_busy=False

    def credentials(self):
        if not self.secret_path.exists():return {}
        try:return json.loads(self.secret_path.read_text(encoding='utf-8'))
        except (OSError,json.JSONDecodeError):return {}

    def save(self,body):
        client=str(body.get('client_id','')).strip();token=str(body.get('access_token','')).strip()
        if not client.isdigit() or not token or len(token)>10000 or any(c in token for c in '\r\n'):raise ValueError('Numeric Dhan Client ID and valid access token required')
        with self.lock:
            tmp=self.secret_path.with_suffix('.tmp')
            fd=os.open(tmp,os.O_WRONLY|os.O_CREAT|os.O_TRUNC,0o600)
            with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump({'client_id':client,'access_token':token},f)
            tmp.replace(self.secret_path);self.revision+=1;self.rows={};self.verified=False;self.state='SAVED_UNVERIFIED'
        return {'saved':True,'note':'Credentials saved privately. Test connection to verify account.'}

    def request(self,url,authenticated=False,payload=None):
        allowed={MASTER,'https://api.dhan.co/v2/profile','https://api.dhan.co/v2/charts/intraday'}
        if url not in allowed:raise ValueError('Only allowlisted data URLs permitted')
        headers={'User-Agent':'CurveDesk/0.1','Accept':'application/json'}
        if authenticated:
            cfg=self.credentials()
            if not cfg.get('access_token'):raise ValueError('Connect Dhan in Settings first')
            headers['access-token']=cfg['access_token']
            if payload is not None:headers['client-id']=cfg['client_id'];headers['Content-Type']='application/json'
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):raise ValueError('Provider redirect refused')
        req=urllib.request.Request(url,headers=headers,data=json.dumps(payload).encode() if payload is not None else None)
        try:
            with urllib.request.build_opener(NoRedirect).open(req,timeout=25) as response:data=response.read(80_000_001)
            if len(data)>80_000_000:raise ValueError('Provider response too large')
            return data.decode('utf-8-sig') if url==MASTER else json.loads(data)
        except urllib.error.HTTPError as e:
            raise ValueError(f'Dhan HTTP {e.code}. Check token validity, Client ID and data entitlement.') from None
        except (urllib.error.URLError,TimeoutError,json.JSONDecodeError):raise ValueError('Dhan connection/response failed; no data invented') from None

    def test(self):
        cfg=self.credentials();r=self.request('https://api.dhan.co/v2/profile',True)
        if str(r.get('dhanClientId',''))!=cfg.get('client_id'):raise ValueError('Token belongs to a different Client ID, or profile response invalid')
        self.verified=True
        return {k:r.get(k) for k in ('tokenValidity','activeSegment','dataPlan','dataValidity')}

    def refresh_catalogue(self):
        with self.lock:
            if self.catalogue_busy:return {'running':True}
            self.catalogue_busy=True
        def worker():
            try:
                rows=parse_master(self.request(MASTER))
                with self.store.db() as c:
                    c.execute('DELETE FROM contracts');c.executemany('INSERT INTO contracts VALUES(?,?)',[(r['id'],json.dumps(r)) for r in rows])
                self.store.set('catalogue_time',time.time());self.catalogue_error=None;self.revision+=1
            except Exception as e:self.catalogue_error=str(e) if isinstance(e,ValueError) else 'Catalogue refresh failed; previous rows retained'
            finally:self.catalogue_busy=False
        threading.Thread(target=worker,daemon=True).start()
        return {'running':True}

    def history(self,body):
        contracts={c['id']:c for c in self.store.rows('contracts')};sid=str(body.get('id'))
        if sid not in contracts:raise ValueError('Choose an active catalogue contract')
        dates=[]
        for key in ('from','to'):
            try:dates.append(datetime.strptime(str(body.get(key)),'%Y-%m-%d'))
            except ValueError:raise ValueError('History dates must be YYYY-MM-DD') from None
        if not 0<(dates[1]-dates[0]).days<=30:raise ValueError('Choose a history range of 1–30 days')
        interval=str(body.get('interval','15'))
        if interval not in ('1','5','15','25','60'):raise ValueError('Unsupported historical interval')
        result=self.request('https://api.dhan.co/v2/charts/intraday',True,{'securityId':sid,'exchangeSegment':'MCX_COMM','instrument':'FUTCOM','interval':interval,'oi':True,'fromDate':body['from']+' 00:00:00','toDate':body['to']+' 00:00:00'})
        if result.get('status')=='failure':raise ValueError('Dhan rejected historical data request')
        return {'contract':contracts[sid],'data':result,'basis':'Individual contract historical candles. Not historical executable spread/depth.'}

    def status(self):
        return {'state':self.state,'error':self.error,'configured':bool(self.credentials()),'profile_verified':self.verified,
                'last_packet':self.last_packet,'quotes':len(self.rows),'catalogue_busy':self.catalogue_busy,'catalogue_error':self.catalogue_error}

    def snapshot(self):
        with self.lock:return dict(self.rows)

    def loop(self):
        backoff=3
        while not self.stop.is_set():
            cfg=self.credentials();contracts=self.store.rows('contracts');revision=self.revision
            if not cfg or not contracts:
                self.state='NOT_CONFIGURED' if not cfg else 'WAITING_CATALOGUE';self.stop.wait(2);continue
            try:
                from websockets.sync.client import connect
                logger=logging.getLogger('curvedesk.dhan');logger.disabled=True
                url='wss://api-feed.dhan.co?'+urlencode({'version':'2','token':cfg['access_token'],'clientId':cfg['client_id'],'authType':'2'})
                with connect(url,open_timeout=20,ping_interval=10,ping_timeout=30,close_timeout=3,max_queue=1024,max_size=2_000_000,logger=logger) as ws:
                    with self.lock:self.rows={};self.state='SUBSCRIBED';self.error=None
                    ids=[r['id'] for r in contracts]
                    if len(ids)>5000:raise ValueError('Catalogue exceeds one-connection subscription limit')
                    for i in range(0,len(ids),100):
                        chunk=ids[i:i+100];ws.send(json.dumps({'RequestCode':21,'InstrumentCount':len(chunk),'InstrumentList':[{'ExchangeSegment':'MCX_COMM','SecurityId':sid} for sid in chunk]}))
                        if i+100<len(ids):self.stop.wait(.05)
                    backoff=3
                    while not self.stop.is_set() and revision==self.revision:
                        try:raw=ws.recv(timeout=2)
                        except TimeoutError:continue
                        if not isinstance(raw,bytes):raise ValueError('Unexpected Dhan feed response')
                        for sid,q in decode(raw):
                            with self.lock:
                                old=self.rows.get(sid)
                                if old and q['trade_time']<old['trade_time']:continue
                                self.rows[sid]=q;self.state='RECEIVING';self.last_packet=q['received_at']
            except Exception as e:
                # Never expose transport exceptions: URL may contain the access token.
                self.error=str(e) if type(e) is ValueError else 'Dhan feed unavailable. Verify credentials/data plan; automatic reconnect active.'
                self.state='DISCONNECTED'
            finally:
                with self.lock:self.rows={}
            self.stop.wait(backoff);backoff=min(60,backoff*2)
