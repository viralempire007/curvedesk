import copy
import io
import json
import math
import sqlite3
import struct
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
import zipfile
from pathlib import Path
from unittest.mock import patch
from curvedesk import analytics as a
from curvedesk.desk import Desk
from curvedesk.dhan import decode,parse_master
from curvedesk.server import create_server


def quote(bid=100,ask=101,now=None,quantity=100):
    now=time.time() if now is None else now
    return {'bid':bid,'ask':ask,'last':bid,'received_at':now,'trade_time':int(now),'volume':100,'oi':50,
            'depth':{'buy':[{'price':bid,'quantity':quantity}],'sell':[{'price':ask,'quantity':quantity}]}}


def spec(multiplier=10,quantity=100,unit='g',depth_units=1):
    return {'multiplier':multiplier,'quantity':quantity,'unit':unit,'depth_units':depth_units,'confirmed':True}


def seeded(directory):
    desk=Desk(directory)
    near={'id':'1','symbol':'GOLD','expiry':'2099-01-01','label':'GOLD Jan 2099','lot_units':1,'tick':1}
    far={**near,'id':'2','expiry':'2099-02-01','label':'GOLD Feb 2099'}
    with desk.store.db() as c:c.executemany('INSERT INTO contracts VALUES(?,?)',[(r['id'],json.dumps(r)) for r in (near,far)])
    desk.store.set('catalogue_time',time.time());desk.save_spec({'symbol':'GOLD',**spec()})
    desk.save_settings({'brokerage_per_crore':0,'costs_confirmed':True})
    d=desk.save_pair({'near':'1','far':'2','window':30})
    return desk,d


class AnalyticsTests(unittest.TestCase):
    def test_validation(self):
        for x in (None,True,float('nan'),float('inf'),-1):
            with self.assertRaises(ValueError):a.number(x,'test')
        for x in (0,1.5,10001,True):
            with self.assertRaises(ValueError):a.whole(x,'lots')

    def test_depth_weighted_average_and_insufficiency(self):
        q=quote();q['depth']['sell']=[{'price':101,'quantity':1},{'price':102,'quantity':2}]
        self.assertAlmostEqual(a.fill(q,'BUY',3)['price'],305/3)
        self.assertIsNone(a.fill(q,'BUY',4)['price'])
        q['depth']['sell'].append({'price':102,'quantity':2})
        self.assertIsNone(a.fill(q,'BUY',4)['price'])

    def test_separate_leg_multipliers_and_balanced_physical_units(self):
        r=a.execution([quote(),quote(120,121)],[spec(100,1000),spec(10,100)],[1,10],'LONG',{'rate':.00012,'other':2})
        self.assertEqual(r['entry'],-1900);self.assertEqual(r['friction'],200)
        self.assertAlmostEqual(r['fees'],44200*.00012+22);self.assertTrue(r['exposure']['balanced'])

    def test_scenario_signs_no_double_slippage(self):
        prices=[100,120,110,125];cost={'rate':0,'other':0}
        self.assertEqual(a.scenario(prices,[spec(),spec()],[1,1],'LONG',cost)['net'],50)
        self.assertEqual(a.scenario(prices,[spec(),spec()],[1,1],'SHORT',cost)['net'],-50)
        r=a.scenario(prices,[spec(),spec()],[1,2],'LONG',cost)
        self.assertEqual(r['net'],0);self.assertFalse(r['exposure']['balanced']);self.assertIsNone(r['return_pct'])
        with self.assertRaises(ValueError):a.scenario(prices,[spec(),spec()],[1,1],'typo',cost)

    def test_depth_units_not_lot_count(self):
        r=a.execution([quote(quantity=10),quote(120,121,quantity=10)],[spec(depth_units=5),spec(depth_units=5)],[2,3],'SHORT',{'rate':0,'other':0})
        self.assertFalse(r['capacity']);self.assertIsNone(r['entry']);self.assertEqual(r['entries'][1]['required'],15)

    def test_physical_unit_conversion(self):
        self.assertTrue(a.exposure([spec(quantity=1,unit='kg'),spec(quantity=100,unit='g')],[1,10])['balanced'])
        with self.assertRaises(ValueError):a.exposure([spec(unit='kg'),spec(unit='barrel')],[1,1])

    def test_quality_not_volume_direction(self):
        qs=[quote(now=1000),quote(now=1000)];self.assertFalse(a.quality(qs,1001))
        for bad in ({'received_at':980},{'received_at':1005},{'received_at':997},{'ask':99}):
            rows=copy.deepcopy(qs);rows[1].update(bad);self.assertTrue(a.quality(rows,1001))
        qs[0]['volume']=0;self.assertFalse(a.quality(qs,1001))

    def test_indicators_negative_zero_and_missing_bars(self):
        bars=[{'time':i*60,'open':-100+i,'high':-98+i,'low':-102+i,'close':-100+i,'samples':3} for i in range(40)]
        r=a.indicators(bars,60,2400,30);self.assertEqual(r['atr'],4);self.assertEqual(r['direction'],'UP');self.assertEqual(r['change_atr'],.25)
        bars.pop(30);self.assertEqual(a.indicators(bars,60,2400,30)['bars'],9)
        self.assertIsNone(a.indicators(bars,60,2400,30)['atr']);self.assertEqual(a.indicators(bars,60,9999,30)['bars'],0)
        flat=[{'time':i*60,'high':0,'low':0,'close':0,'samples':3} for i in range(35)]
        self.assertIsNone(a.indicators(flat,60,2100,30)['z'])

    def test_full_binary_packet(self):
        packet=bytearray(162);struct.pack_into('<BHBI',packet,0,8,162,5,42)
        struct.pack_into('<f',packet,8,123);struct.pack_into('<I',packet,14,1000)
        struct.pack_into('<I',packet,22,200);struct.pack_into('<I',packet,34,300)
        for i in range(5):struct.pack_into('<IIHHff',packet,62+20*i,10+i,20+i,1,1,122-i,124+i)
        sid,q=decode(bytes(packet),1001)[0]
        self.assertEqual(sid,'42');self.assertEqual(q['bid'],122);self.assertEqual(q['ask'],124);self.assertEqual(q['volume'],200);self.assertEqual(q['oi'],300)
        self.assertEqual(len(q['depth']['buy']),5)
        with self.assertRaises(ValueError):decode(packet[:100])
        disconnect=struct.pack('<BHBIH',50,10,5,0,807)
        with self.assertRaisesRegex(ValueError,'807'):decode(disconnect)

    def test_master_filters_futures_and_expiry(self):
        text='EXCH_ID,INSTRUMENT,SECURITY_ID,SYMBOL_NAME,SM_EXPIRY_DATE,LOT_SIZE,TICK_SIZE\nMCX,FUTCOM,1,GOLD,2099-01-01,1,1\nMCX,OPTFUT,2,GOLD,2099-01-01,1,1\nMCX,FUTCOM,3,GOLD,2000-01-01,1,1\n'
        self.assertEqual(len(parse_master(text,today='2026-01-01')),1)
        with self.assertRaises(ValueError):parse_master('bad,csv')


class DeskTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.d,self.p=seeded(self.temp.name);self.key=self.p['key'];self.now=time.time()
    def tearDown(self):self.temp.cleanup()
    def observe(self,now,rows=None):
        rows=rows or {'1':quote(now=now),'2':quote(120,121,now)}
        self.d.dhan.rows=rows;self.d.observe(rows,now);return rows

    def test_no_cached_or_out_of_order_recording(self):
        rows=self.observe(self.now);self.observe(self.now+1,rows)
        self.observe(self.now+2,{'1':quote(now=self.now-1),'2':quote(120,121,self.now+2)})
        self.assertEqual(len(self.d.report(self.key,self.now+2)['samples']),1)

    def test_one_leg_updates_are_real_possible_movement(self):
        rows=self.observe(self.now);rows={**rows,'1':quote(105,106,self.now+1)};self.observe(self.now+1,rows)
        samples=self.d.report(self.key,self.now+1)['samples'];self.assertEqual(samples[-1]['mid']-samples[0]['mid'],50)

    def test_stale_quote_no_executable_claim(self):
        self.observe(self.now);r=self.d.report(self.key,self.now+20)
        self.assertEqual(r['classification'],'DATA_UNRELIABLE');self.assertFalse(r['ratios']);self.assertEqual(r['candidate']['state'],'WAIT')

    def test_spec_change_blocks_and_resets(self):
        self.observe(self.now);self.d.save_spec({'symbol':'GOLD',**spec(multiplier=20)})
        self.assertTrue(self.d.report(self.key,self.now)['errors'])
        self.d.save_pair({'near':'1','far':'2'});self.assertFalse(self.d.report(self.key,self.now)['samples'])

    def test_unconfirmed_specs_rejected(self):
        self.d.store.set('specs',{})
        with self.assertRaises(ValueError):self.d.save_pair({'near':'1','far':'2'})
        with self.assertRaises(ValueError):self.d.save_spec({'symbol':'GOLD','confirmed':False})

    def test_volume_reset_and_gap_not_synthesized(self):
        self.observe(self.now);rows={'1':quote(now=self.now+3600),'2':quote(120,121,self.now+3600)};rows['1']['volume']=1
        self.observe(self.now+3600,rows);r=self.d.report(self.key,self.now+3600)
        self.assertEqual(len(r['samples']),2);self.assertIsNone(r['samples'][-1]['leg_volume_changes'][0]);self.assertIsNone(r['movement']['change_60s'])

    def test_costs_margin_and_ratio_sensitivity(self):
        r=self.d.compare({'key':self.key,'near_entry':100,'far_entry':120,'near_exit':110,'far_exit':125,'margins':{'1:2':1000}})
        rows={x['ratio']:x for x in r['rows']};self.assertEqual(rows['1:1']['net'],50);self.assertEqual(rows['1:2']['net'],0);self.assertEqual(rows['1:2']['return_pct'],0)
        with self.assertRaises(ValueError):self.d.compare({'key':self.key,'near_entry':100,'far_entry':120,'near_exit':110,'far_exit':125,'margins':{'1:1':0}})

    def test_persistence_backup_and_excluded_credentials(self):
        self.observe(self.now);self.d.dhan.save({'client_id':'123','access_token':'TEST-SECRET-DO-NOT-SHARE'})
        raw=self.d.store.backup()
        with zipfile.ZipFile(io.BytesIO(raw)) as z:self.assertNotIn(b'TEST-SECRET',z.read('curvedesk.db'))
        self.d.delete_pair(self.key);self.assertFalse(self.d.definitions());self.d.store.restore(raw)
        self.assertEqual(self.d.definitions()[0]['key'],self.key)
        other=Desk(self.temp.name);self.assertEqual(len(other.definitions()),1)
        self.assertTrue((Path(self.temp.name)/'before-restore.zip').exists())

    def test_corrupt_backup_refused(self):
        with self.assertRaises(ValueError):self.d.store.restore(b'not a zip')
        raw=self.d.store.backup();out=io.BytesIO()
        with zipfile.ZipFile(io.BytesIO(raw)) as old,zipfile.ZipFile(out,'w') as z:
            for name in old.namelist():z.writestr(name,b'bad' if name=='curvedesk.db' else old.read(name))
        with self.assertRaises(ValueError):self.d.store.restore(out.getvalue())

    def test_one_open_position_and_frozen_levels(self):
        self.observe(self.now);plan={'state':'RESEARCH_CANDIDATE','side':'LONG','entry':-190,'tp1':-180,'tp2':-170,'stop':-220}
        with patch.object(self.d,'plan',return_value=plan):
            trade=self.d.trade({'action':'OPEN','key':self.key,'near_fill':101,'far_fill':120})
            with self.assertRaises(ValueError):self.d.trade({'action':'OPEN','key':self.key,'near_fill':101,'far_fill':120})
        self.observe(self.now+1,{'1':quote(105,106,self.now+1),'2':quote(120,121,self.now+1)})
        self.d.observe(self.d.dhan.rows,self.now+2)
        stored=self.d.store.rows('trades')[0];self.assertEqual(stored['plan'],plan);self.assertIsNotNone(stored['marked_net'])
        self.assertEqual(len(self.d.alerts()),1)
        closed=self.d.trade({'action':'CLOSE','id':trade['id'],'near_exit':110,'far_exit':125,'actual_fees':3})
        self.assertEqual(closed['net'],37)

    def test_structural_candidate_uses_own_history_and_cost_filters(self):
        bars=[{'time':i*60,'high':2,'low':-12,'close':0,'samples':3} for i in range(60)]
        tech={'bars':60,'z':-2.5,'change':1,'atr':2}
        self.d.save_settings({'min_net':1,'risk_budget':1000,'min_rr':1})
        selected={'long':{'capacity':True,'entry':-10,'fees':1}}
        plan=self.d.plan(self.p,bars,tech,selected,[],3600)
        self.assertEqual(plan['state'],'RESEARCH_CANDIDATE');self.assertEqual(plan['side'],'LONG')
        self.assertEqual(plan['tp2'],0);self.assertEqual(plan['stop'],-14)
        self.d.save_settings({'min_net':100})
        self.assertEqual(self.d.plan(self.p,bars,tech,selected,[],3600)['state'],'WAIT')
        unequal={**self.p,'exposure':{'balanced':False}}
        self.assertEqual(self.d.plan(unequal,bars,tech,selected,[],3600)['state'],'WAIT')

    def test_storage_prunes_stale_raw_samples(self):
        self.observe(self.now)
        self.observe(self.now+86461)
        with self.d.store.db() as c:
            self.assertEqual(c.execute('SELECT COUNT(*) FROM samples').fetchone()[0],1)

    def test_bad_settings_and_pairs(self):
        for body in ({'window':True},{'timeframe':0},{'near_lots':1.5},{'near':'2','far':'1'}):
            with self.assertRaises(ValueError):self.d.save_pair({'near':'1','far':'2',**body})
        with self.assertRaises(ValueError):self.d.save_settings({'risk_budget':float('nan')})


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.d,self.p=seeded(self.temp.name)
        self.http=create_server(self.d,0);self.thread=threading.Thread(target=self.http.serve_forever,daemon=True);self.thread.start();self.url='http://127.0.0.1:'+str(self.http.server_port)
    def tearDown(self):self.http.shutdown();self.http.server_close();self.thread.join();self.temp.cleanup()
    def request(self,path,body=None,headers=None):
        h={'Content-Type':'application/json','X-CurveDesk':'1',**(headers or {})}
        return urllib.request.urlopen(urllib.request.Request(self.url+path,headers=h,data=json.dumps(body).encode() if body is not None else None),timeout=3)
    def test_assets_and_security_headers(self):
        with self.request('/') as r:self.assertIn(b'CurveDesk',r.read());self.assertIn("script-src 'self'",r.headers['Content-Security-Policy'])
        for path in ('/app.js','/style.css','/icon.svg','/api/status','/api/contracts','/api/settings','/api/pairs','/api/trades','/api/report/'+self.p['key']):
            with self.request(path) as r:self.assertEqual(r.status,200)
    def test_no_order_endpoints_cross_origin_or_missing_header(self):
        for path,body,headers,code in [('/api/orders',{},None,404),('/api/settings',{}, {'Origin':'https://evil.example'},403),('/api/settings',{}, {'X-CurveDesk':'0'},403),('/api/status',None,{'Host':'evil.example'},403)]:
            with self.assertRaises(urllib.error.HTTPError) as ctx:self.request(path,body,headers)
            self.assertEqual(ctx.exception.code,code)
    def test_token_save_never_returns_secret(self):
        with self.request('/api/connect',{'client_id':'123','access_token':'MY_TEST_TOKEN'}) as r:self.assertNotIn(b'MY_TEST_TOKEN',r.read())
        for path in ('/api/status','/api/settings'):
            with self.request(path) as r:self.assertNotIn(b'MY_TEST_TOKEN',r.read())
        with patch.object(self.d.dhan,'request',return_value={'dhanClientId':'456'}):
            with self.assertRaises(ValueError):self.d.dhan.test()


if __name__=='__main__':unittest.main()
