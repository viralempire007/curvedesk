"""Deterministic research, recording, frozen plans and user-reported manual trades."""
import json
import math
import statistics
import threading
import time
from datetime import datetime
from fractions import Fraction
from . import analytics as a
from .dhan import Dhan, IST
from .storage import Store

# Display suggestions only. User confirmation or authoritative import is required.
SUGGESTIONS={
 'GOLD':(100,1000,'g'),'GOLDM':(10,100,'g'),'GOLDTEN':(1,10,'g'),
 'GOLDGUINEA':(1,8,'g'),'GOLDPETAL':(1,1,'g'),
 'SILVER':(30,30,'kg'),'SILVERM':(5,5,'kg'),'SILVERMIC':(1,1,'kg'),
 'COPPER':(2500,2500,'kg'),'ALUMINIUM':(5000,5,'tonne'),'ALUMINI':(1000,1,'tonne'),
 'ZINC':(5000,5,'tonne'),'ZINCMINI':(1000,1,'tonne'),'LEAD':(5000,5,'tonne'),'LEADMINI':(1000,1,'tonne'),
 'CRUDEOIL':(100,100,'barrel'),'CRUDEOILM':(10,10,'barrel'),
 'NATURALGAS':(1250,1250,'mmBtu'),'NATGASMINI':(250,250,'mmBtu')}
FAMILIES={'GOLD':['GOLD','GOLDM','GOLDTEN','GOLDGUINEA','GOLDPETAL'],'SILVER':['SILVER','SILVERM','SILVERMIC'],
          'ALUMINIUM':['ALUMINIUM','ALUMINI'],'ZINC':['ZINC','ZINCMINI'],'LEAD':['LEAD','LEADMINI'],
          'CRUDEOIL':['CRUDEOIL','CRUDEOILM'],'NATURALGAS':['NATURALGAS','NATGASMINI']}


def family(symbol):return next((k for k,v in FAMILIES.items() if symbol in v),symbol)


class Desk:
    def __init__(self,directory=None):
        self.store=Store(directory);self.dhan=Dhan(self.store);self.stop=threading.Event();self.lock=threading.RLock()
        self.error=None;self.last_prune=0;self.started=False

    def settings(self):
        config=self.store.get('config',{})
        return {'brokerage_per_crore':config.get('brokerage_per_crore',1200),
                'other_roundtrip_per_leg_lot':config.get('other_roundtrip_per_leg_lot',0),
                'costs_confirmed':config.get('costs_confirmed',False),'min_net':config.get('min_net',200),
                'risk_budget':config.get('risk_budget',2000),'min_rr':config.get('min_rr',1.5),
                'delivery_buffer_days':config.get('delivery_buffer_days',7),
                'specs':self.store.get('specs',{})}

    def save_settings(self,body):
        prior=self.settings()
        for key,max_ in [('brokerage_per_crore',100000),('other_roundtrip_per_leg_lot',100000),('min_net',1e8),('risk_budget',1e8),('min_rr',100),('delivery_buffer_days',90)]:
            if key in body:
                n=a.number(body[key],key,positive=key in ('risk_budget','min_rr'))
                if n>max_:raise ValueError(key+' exceeds supported range')
                prior[key]=n
        prior['costs_confirmed']=body.get('costs_confirmed',prior['costs_confirmed']) is True
        self.store.set('config',{k:v for k,v in prior.items() if k!='specs'})
        return self.settings()

    def save_spec(self,body):
        symbol=str(body.get('symbol',''))
        if symbol not in {c['symbol'] for c in self.store.rows('contracts')}:raise ValueError('Choose a catalogue symbol')
        if body.get('confirmed') is not True:raise ValueError('Confirm current contract quotation and depth units before saving')
        result={key:a.number(body.get(key),key,positive=True) for key in ('multiplier','quantity','depth_units')}
        if any(v>1e9 for v in result.values()):raise ValueError('Specification outside supported range')
        result['unit']=body.get('unit')
        if result['unit'] not in ('g','kg','tonne','barrel','mmBtu'):raise ValueError('Unsupported contract unit')
        result['confirmed']=True
        with self.lock:
            specs=self.store.get('specs',{});specs[symbol]=result;self.store.set('specs',specs)
        return {'saved':symbol,'specification':result}

    def cost(self):
        s=self.settings();return {'rate':s['brokerage_per_crore']/10_000_000,'other':s['other_roundtrip_per_leg_lot']}

    def catalogue(self):
        contracts=self.store.rows('contracts');symbols=sorted({c['symbol'] for c in contracts})
        return {'contracts':contracts,'symbols':symbols,'updated':self.store.get('catalogue_time'),
                'spec_suggestions':{s:{'multiplier':SUGGESTIONS[s][0],'quantity':SUGGESTIONS[s][1],'unit':SUGGESTIONS[s][2],'depth_units':1,'confirmed':False} for s in symbols if s in SUGGESTIONS},
                'note':'Built-in specification suggestions are unverified; confirm current exchange quotation and broker depth units.'}

    def definitions(self):return self.store.rows('pairs')

    def save_pair(self,body):
        mapping={c['id']:c for c in self.store.rows('contracts')};near=mapping.get(str(body.get('near')));far=mapping.get(str(body.get('far')))
        if not near or not far or near['expiry']>=far['expiry']:raise ValueError('Select near and later far expiry from the active catalogue')
        if family(near['symbol'])!=family(far['symbol']):raise ValueError('Only the same underlying commodity is supported')
        lots=[a.whole(body.get(k,1),k) for k in ('near_lots','far_lots')]
        timeframe=body.get('timeframe',60);window=body.get('window',60)
        if isinstance(timeframe,bool) or timeframe not in (60,300,900):raise ValueError('Choose 1m, 5m or 15m bars')
        if isinstance(window,bool) or not isinstance(window,int) or not 30<=window<=240:raise ValueError('Z-score window must be 30–240 bars')
        specs=self.store.get('specs',{});leg_specs=[specs.get(c['symbol']) for c in (near,far)]
        if not all(s and s.get('confirmed') for s in leg_specs):raise ValueError('Confirm specifications for both variants in Settings first')
        physical=a.exposure(leg_specs,lots);key=f"{near['id']}:{far['id']}:{lots[0]}:{lots[1]}"
        record={'key':key,'near':near,'far':far,'lots':lots,'timeframe':timeframe,'window':window,'specs':leg_specs,'exposure':physical}
        with self.lock,self.store.db() as c:
            old=c.execute('SELECT payload FROM pairs WHERE key=?',(key,)).fetchone()
            if not old and c.execute('SELECT COUNT(*) FROM pairs').fetchone()[0]>=20:raise ValueError('Maximum 20 recorded baskets; remove one first')
            if old:
                previous=json.loads(old[0])
                if any(previous[k]!=record[k] for k in ('specs','timeframe')):
                    c.execute('DELETE FROM samples WHERE key=?',(key,));c.execute('DELETE FROM bars WHERE key=?',(key,))
            c.execute('INSERT OR REPLACE INTO pairs VALUES(?,?)',(key,json.dumps(record)))
        return record

    def delete_pair(self,key):
        with self.lock,self.store.db() as c:
            if c.execute("SELECT 1 FROM trades WHERE key=? AND status='OPEN'",(key,)).fetchone():raise ValueError('Close the manual trade record before removing this basket')
            c.execute('DELETE FROM pairs WHERE key=?',(key,))
            c.execute('DELETE FROM samples WHERE key=?',(key,))
            c.execute('DELETE FROM bars WHERE key=?',(key,))
        return {'deleted':key}

    def pair_errors(self,d):
        specs=self.store.get('specs',{});errors=[]
        if any(specs.get(c['symbol'])!=s for c,s in zip((d['near'],d['far']),d['specs'])):errors.append('Contract specifications changed; save basket again to restart baseline')
        today=datetime.now(IST).date()
        days=min((datetime.strptime(c['expiry'],'%Y-%m-%d').date()-today).days for c in (d['near'],d['far']))
        if days<=self.settings()['delivery_buffer_days']:errors.append('Inside configured expiry/delivery buffer; choose later expiries')
        updated=self.store.get('catalogue_time')
        if not updated or not 0<=time.time()-updated<=36*3600:errors.append('Catalogue older than 36 hours; refresh catalogue')
        return errors

    def balanced_lots(self,d):
        specs=d['specs'];factors={'g':1,'kg':1000,'tonne':1000000,'barrel':1,'mmBtu':1}
        q=[s['quantity']*factors[s['unit']] for s in specs];ratio=Fraction(str(q[1]))/Fraction(str(q[0]))
        return [ratio.numerator,ratio.denominator] if max(ratio.numerator,ratio.denominator)<=10000 else None

    def ratios(self,d):
        values=[d['lots'],[1,1],[1,2],[2,3]];balanced=self.balanced_lots(d)
        if balanced:values.append(balanced)
        return [list(x) for x in dict.fromkeys(tuple(v) for v in values)]

    def observe(self,quotes,now=None):
        now=time.time() if now is None else now
        for d in self.definitions():
            qs=[quotes.get(c['id']) for c in (d['near'],d['far'])]
            if self.pair_errors(d) or a.quality(qs,now):continue
            signature=[q['received_at'] for q in qs];weights=[s['multiplier']*n for s,n in zip(d['specs'],d['lots'])]
            with self.lock,self.store.db() as c:
                previous=c.execute('SELECT payload FROM samples WHERE key=? ORDER BY id DESC LIMIT 1',(d['key'],)).fetchone()
                old=json.loads(previous[0]) if previous else None
                if old and (old['signature']==signature or any(x<y for x,y in zip(signature,old['signature']))):continue
                mid=sum((q['bid']+q['ask'])/2*w*sign for q,w,sign in zip(qs,weights,(1,-1)))
                long=a.execution(qs,d['specs'],d['lots'],'LONG',self.cost());short=a.execution(qs,d['specs'],d['lots'],'SHORT',self.cost())
                deltas=[]
                for i,q in enumerate(qs):
                    prev=old['quotes'][i] if old else None
                    same_day=prev and datetime.fromtimestamp(prev['received_at'],IST).date()==datetime.fromtimestamp(q['received_at'],IST).date()
                    delta=q['volume']-prev['volume'] if same_day else None
                    deltas.append(delta if delta is not None and delta>=0 else None)
                row={'time':now,'mid':mid,'ltp':sum(q['last']*w*sign for q,w,sign in zip(qs,weights,(1,-1))),
                     'signature':signature,'buy':long['entry'],'sell':short['entry'],'quotes':qs,'leg_volume_changes':deltas}
                c.execute('INSERT INTO samples(key,observed,payload) VALUES(?,?,?)',(d['key'],now,json.dumps(row,allow_nan=False)))
                bucket=int(now//d['timeframe'])*d['timeframe']
                c.execute('''INSERT INTO bars VALUES(?,?,?,?,?,?,1) ON CONFLICT(key,bucket) DO UPDATE SET
                 high=MAX(high,excluded.high),low=MIN(low,excluded.low),close=excluded.close,samples=samples+1''',(d['key'],bucket,mid,mid,mid,mid))
        if now-self.last_prune>=60:
            with self.store.db() as c:
                c.execute('DELETE FROM samples WHERE observed<?',(now-86400,))
                c.execute('DELETE FROM samples WHERE id <= COALESCE((SELECT id FROM samples ORDER BY id DESC LIMIT 1 OFFSET 100000),-1)')
                c.execute('DELETE FROM bars WHERE bucket<?',(now-90*86400,))
                c.execute('DELETE FROM bars WHERE rowid IN (SELECT rowid FROM bars ORDER BY bucket DESC LIMIT -1 OFFSET 100000)')
            self.last_prune=now
        self.monitor_trades(quotes,now)

    def report(self,key,now=None):
        now=time.time() if now is None else now;d=next((r for r in self.definitions() if r['key']==key),None)
        if not d:raise ValueError('Unknown basket')
        with self.store.db() as c:
            samples=[json.loads(r[0]) for r in c.execute('SELECT payload FROM samples WHERE key=? ORDER BY id DESC LIMIT 900',(key,))][::-1]
            bars=[dict(r) for r in c.execute('SELECT bucket time,open,high,low,close,samples FROM bars WHERE key=? ORDER BY bucket DESC LIMIT 1000',(key,))][::-1]
        quotes=self.dhan.snapshot();qs=[quotes.get(c['id']) for c in (d['near'],d['far'])]
        errors=self.pair_errors(d)+a.quality(qs,now);tech=a.indicators(bars,d['timeframe'],now,d['window']);ratios=[]
        if not errors:
            for lots in self.ratios(d):ratios.append({'ratio':':'.join(map(str,lots)),**{side.lower():a.execution(qs,d['specs'],lots,side,self.cost()) for side in ('LONG','SHORT')}})
        selected=next((r for r in ratios if r['ratio']==':'.join(map(str,d['lots']))),None)
        movement={'change_60s':None,'elapsed':None,'long_mark_net':None,'short_mark_net':None}
        anchors=[s for s in samples if 60<=now-s['time']<=70]
        if anchors and samples and now-samples[-1]['time']<=10:
            before=anchors[-1];last=samples[-1];movement.update(change_60s=last['mid']-before['mid'],elapsed=last['time']-before['time'])
            if not errors:
                for side in ('LONG','SHORT'):
                    old=a.execution(before['quotes'],d['specs'],d['lots'],side,self.cost());current=selected[side.lower()]
                    if old['capacity'] and current['capacity']:
                        prices=[old['entries'][0]['price'],old['entries'][1]['price'],current['exits'][0]['price'],current['exits'][1]['price']]
                        movement[side.lower()+'_mark_net']=a.scenario(prices,d['specs'],d['lots'],side,self.cost())['net']
        classification='DATA_UNRELIABLE' if errors else 'COLLECTING_BASELINE'
        if selected:
            if not selected['long']['capacity']:classification='INSUFFICIENT_VISIBLE_DEPTH'
            elif movement['change_60s'] is not None:classification='QUOTED_MOVEMENT' if abs(movement['change_60s'])>1e-9 else 'NO_NET_QUOTED_MOVEMENT'
        candidate=self.plan(d,bars,tech,selected,errors,now)
        return {'definition':d,'quotes':qs,'errors':list(dict.fromkeys(errors)),'technical':tech,'classification':classification,
                'ratios':ratios,'samples':samples,'bars':bars,'movement':movement,'candidate':candidate,'as_of':now,
                'basis':'Weighted near−far midpoint, sampled once/second. Exchange depth timestamp unavailable. No confirmed spread volume or manipulation classification.'}

    def plan(self,d,bars,tech,selected,errors,now):
        reasons=list(errors);cfg=self.settings()
        if not cfg['costs_confirmed']:reasons.append('Confirm actual brokerage and all applicable charges in Settings')
        if tech['bars']<max(60,d['window']):reasons.append('Need at least 60 consecutive completed observed bars for structural research')
        if not selected or not selected['long']['capacity']:reasons.append('Insufficient fresh quantity-aware depth')
        if not d['exposure']['balanced']:reasons.append('Unequal physical exposure: use scenario comparison; automatic calendar plan disabled')
        if reasons:return {'state':'WAIT','reasons':list(dict.fromkeys(reasons))}
        z,change=tech['z'],tech['change']
        side='LONG' if z is not None and z<=-2 and change>0 else 'SHORT' if z is not None and z>=2 and change<0 else None
        if not side:return {'state':'WAIT','reasons':['No extreme spread deviation with a completed-bar reversal; no forced trade']}
        completed=[b for b in bars if b['time']+d['timeframe']<=now][-d['window']:]
        target=statistics.mean(b['close'] for b in completed);entry=selected[side.lower()]['entry'];atr=tech['atr'] or 0
        stop=min(b['low'] for b in completed)-atr if side=='LONG' else max(b['high'] for b in completed)+atr
        sign=1 if side=='LONG' else -1;reward=sign*(target-entry)-selected[side.lower()]['fees'];risk=sign*(entry-stop)+selected[side.lower()]['fees']
        if reward<=0 or risk<=0 or reward<cfg['min_net'] or risk>cfg['risk_budget'] or reward/risk<cfg['min_rr']:
            return {'state':'WAIT','reasons':['Structure-based target fails net-profit, risk-budget or reward/risk filter'], 'estimated_reward':reward,'estimated_risk':risk}
        return {'state':'RESEARCH_CANDIDATE','side':side,'entry':entry,'tp1':entry+(target-entry)/2,'tp2':target,'stop':stop,
                'estimated_net_tp2':reward,'estimated_risk':risk,'reward_risk':reward/risk,'observed_at':now,
                'basis':'Mean-reversion hypothesis: |Z|≥2 plus completed-bar reversal. TP2 is recent mean; stop beyond observed extreme by observed ATR. Sampled history, no validated win probability. Exit liquidity/fees may change.'}

    def compare(self,body):
        d=next((r for r in self.definitions() if r['key']==body.get('key')),None)
        if not d:raise ValueError('Unknown basket')
        if self.pair_errors(d):raise ValueError('; '.join(self.pair_errors(d)))
        prices=[body.get(k) for k in ('near_entry','far_entry','near_exit','far_exit')];margins=body.get('margins',{})
        if not isinstance(margins,dict):raise ValueError('Margins must be keyed by ratio')
        rows=[]
        for lots in self.ratios(d):
            ratio=':'.join(map(str,lots));margin=margins.get(ratio)
            margin=None if margin in ('',None) else a.number(margin,'broker margin',positive=True)
            r=a.scenario(prices,d['specs'],lots,body.get('side','LONG'),self.cost(),margin)
            rows.append({'ratio':ratio,**r,'minimum_met':r['net']>=self.settings()['min_net']})
        return {'rows':rows,'basis':'User-entered fill scenarios, not forecasts. Fees deducted once; fill prices already include execution. Margin is user-supplied.'}

    def trade(self,body):
        with self.lock:
            if body.get('action')=='OPEN':
                key=str(body.get('key'));report=self.report(key);d=report['definition'];plan=report['candidate']
                if plan['state']!='RESEARCH_CANDIDATE':raise ValueError('A current research candidate is required to freeze monitored levels')
                prices=[a.number(body.get(k),k,positive=True) for k in ('near_fill','far_fill')]
                record={'key':key,'definition':d,'plan':plan,'fills':prices,'opened':time.time(),'state':'OPEN','marked_net':None}
                with self.store.db() as c:
                    if c.execute("SELECT 1 FROM trades WHERE key=? AND status='OPEN'",(key,)).fetchone():raise ValueError('One manual trade per basket is already open')
                    record['id']=c.execute("INSERT INTO trades(key,status,payload) VALUES(?,'OPEN',?)",(key,json.dumps(record))).lastrowid
                    c.execute('UPDATE trades SET payload=? WHERE id=?',(json.dumps(record),record['id']))
                return record
            if body.get('action')!='CLOSE':raise ValueError('Choose OPEN or CLOSE')
            id_=a.whole(body.get('id'),'trade id',2**31)
            with self.store.db() as c:
                row=c.execute("SELECT payload FROM trades WHERE id=? AND status='OPEN'",(id_,)).fetchone()
                if not row:raise ValueError('Open manual trade not found')
                trade=json.loads(row[0]);d=trade['definition'];exits=[a.number(body.get(k),k,positive=True) for k in ('near_exit','far_exit')]
                fees=a.number(body.get('actual_fees'),'actual total fees');result=a.scenario(trade['fills']+exits,d['specs'],d['lots'],trade['plan']['side'],{'rate':0,'other':0})
                trade.update(state='CLOSED',closed=time.time(),exit_fills=exits,actual_fees=fees,net=result['gross']-fees)
                c.execute("UPDATE trades SET status='CLOSED',payload=? WHERE id=?",(json.dumps(trade),id_))
            return trade

    def monitor_trades(self,quotes,now):
        for trade in self.store.rows('trades'):
            if trade['state']!='OPEN':continue
            d=trade['definition'];qs=[quotes.get(c['id']) for c in (d['near'],d['far'])]
            if a.quality(qs,now):continue
            side=trade['plan']['side'];market=a.execution(qs,d['specs'],d['lots'],side,self.cost())
            if not market['capacity']:continue
            exits=[r['price'] for r in market['exits']];net=a.scenario(trade['fills']+exits,d['specs'],d['lots'],side,self.cost())['net']
            trade.update(marked_net=net,marked_at=now,mark_basis='Indicative depth-weighted exit; not an actual fill')
            sign=1 if side=='LONG' else -1;level=market['exit'];plan=trade['plan'];kind=None
            if sign*(level-plan['stop'])<=0:kind='STOP_LEVEL'
            elif sign*(level-plan['tp2'])>=0:kind='TP2_LEVEL'
            elif sign*(level-plan['tp1'])>=0:kind='TP1_LEVEL'
            elif sign*(level-plan['entry'])<0 and abs(level-plan['entry'])>=abs(plan['entry']-plan['stop'])/2:kind='EARLY_EXIT_REVIEW'
            with self.store.db() as c:
                current=c.execute('SELECT status FROM trades WHERE id=?',(trade['id'],)).fetchone()
                if not current or current[0]!='OPEN':continue
                c.execute("UPDATE trades SET payload=? WHERE id=? AND status='OPEN'",(json.dumps(trade),trade['id']))
                alert_key=f"trade:{trade['id']}"
                if kind and not c.execute('SELECT 1 FROM alerts WHERE key=? AND kind=?',(alert_key,kind)).fetchone():
                    c.execute('INSERT INTO alerts(key,kind,created,payload) VALUES(?,?,?,?)',(alert_key,kind,now,json.dumps({'trade_id':trade['id'],'net_mark':net,'message':'Review manual position: '+kind+'. No order was placed.'})))

    def alerts(self):
        with self.store.db() as c:return [dict(r,payload=json.loads(r['payload'])) for r in c.execute('SELECT * FROM alerts ORDER BY id DESC LIMIT 100')]

    def status(self):
        with self.store.db() as c:
            stats={'samples':c.execute('SELECT COUNT(*) FROM samples').fetchone()[0],'bars':c.execute('SELECT COUNT(*) FROM bars').fetchone()[0]}
        return {'version':'0.1.0','mode':'Research only','order_calls':0,'dhan':self.dhan.status(),'recorder_error':self.error,
                'catalogue_updated':self.store.get('catalogue_time'),'recorded_baskets':len(self.definitions()),'archive':stats,
                'retention':'Raw: 24h/100,000 globally. Bars: 90 days/100,000 globally. Earliest limit applies.'}

    def start(self):
        if self.started:return
        self.started=True
        threading.Thread(target=self.dhan.loop,daemon=True).start()
        threading.Thread(target=self.loop,daemon=True).start()
        if not self.store.get('catalogue_time') or time.time()-self.store.get('catalogue_time')>86400:self.dhan.refresh_catalogue()

    def loop(self):
        while not self.stop.wait(1):
            try:
                with self.lock:self.observe(self.dhan.snapshot())
                self.error=None
            except Exception:self.error='Recorder interrupted; check data, specifications and disk space. Prior observations retained.'
