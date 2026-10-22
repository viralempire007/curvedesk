"""All spread signs are near minus far. Monetary weights are separate per leg."""
import math
import statistics


def finite(value):
    if isinstance(value, bool): return None
    try:
        number = float(value)
        return number if math.isfinite(number) else None
    except (ValueError, TypeError, OverflowError): return None


def number(value, name, minimum=0, positive=False):
    result = finite(value)
    if result is None or result < minimum or (positive and result <= 0):
        raise ValueError('Invalid ' + name)
    return result


def whole(value, name, maximum=10000):
    n = number(value, name, positive=True)
    if not n.is_integer() or n > maximum: raise ValueError(name + ' must be whole lots, 1–' + str(maximum))
    return int(n)


def quality(quotes, now):
    if len(quotes) != 2 or not all(quotes): return ['Both live leg quotes required']
    errors=[]
    for q in quotes:
        stamp=finite(q.get('received_at'));bid=finite(q.get('bid'));ask=finite(q.get('ask'))
        if stamp is None or not 0 <= now-stamp <= 10: errors.append('Stale or future-dated quote receipt')
        if bid is None or ask is None or bid <= 0 or ask <= bid: errors.append('Missing, locked or crossed market depth')
    times=[finite(q.get('received_at')) for q in quotes]
    if all(t is not None for t in times) and abs(times[0]-times[1])>2: errors.append('Leg receipt skew exceeds two seconds')
    return list(dict.fromkeys(errors))


def fill(quote, action, required):
    book={}
    for row in quote.get('depth',{}).get('sell' if action=='BUY' else 'buy',[]):
        p,q=finite(row.get('price')),finite(row.get('quantity'))
        if p is not None and q is not None and p>0 and q>0:book[p]=max(book.get(p,0),q)
    left,total=required,0
    for price,qty in sorted(book.items(),reverse=action=='SELL'):
        take=min(left,qty);total+=price*take;left-=take
        if left<=1e-9:break
    return {'price':total/required if left<=1e-9 else None,'required':required,
            'available':sum(book.values()),'sufficient':left<=1e-9}


def exposure(specs,lots):
    scale={'g':1,'kg':1000,'tonne':1000000,'barrel':1,'mmBtu':1}
    units=['mass_g' if s['unit'] in ('g','kg','tonne') else s['unit'] for s in specs]
    if units[0]!=units[1]:raise ValueError('Incompatible physical units')
    values=[s['quantity']*scale[s['unit']]*n for s,n in zip(specs,lots)]
    return {'near':values[0],'far':values[1],'net_long':values[0]-values[1],
            'unit':units[0],'balanced':math.isclose(*values,rel_tol=1e-9)}


def execution(quotes,specs,lots,side,cost):
    if side not in ('LONG','SHORT'):raise ValueError('Invalid side')
    weights=[s['multiplier']*n for s,n in zip(specs,lots)]
    actions=['BUY','SELL'] if side=='LONG' else ['SELL','BUY']
    entries=[fill(q,a,s['depth_units']*n) for q,a,s,n in zip(quotes,actions,specs,lots)]
    exits=[fill(q,'SELL' if a=='BUY' else 'BUY',s['depth_units']*n) for q,a,s,n in zip(quotes,actions,specs,lots)]
    result={'side':side,'lots':lots,'weights':weights,'entries':entries,'exits':exits,
            'exposure':exposure(specs,lots),'capacity':all(r['sufficient'] for r in entries+exits),
            'entry':None,'exit':None,'friction':None,'fees':None,'reversal_cost':None}
    if not result['capacity']:return result
    en=[r['price'] for r in entries];ex=[r['price'] for r in exits]
    entry=en[0]*weights[0]-en[1]*weights[1];exit_=ex[0]*weights[0]-ex[1]*weights[1]
    friction=(1 if side=='LONG' else -1)*(entry-exit_)
    fees=sum((a+b)*w for a,b,w in zip(en,ex,weights))*cost['rate']+sum(lots)*cost['other']
    result.update(entry=entry,exit=exit_,friction=friction,fees=fees,reversal_cost=friction+fees)
    return result


def ema(values,period=20):
    if len(values)<period:return None
    result=statistics.mean(values[:period])
    for v in values[period:]:result+=(v-result)*2/(period+1)
    return result


def indicators(bars,timeframe,now,window=60):
    consecutive=[]
    for b in bars:
        if b['time']+timeframe>now or b['samples']<2:continue
        if consecutive and b['time']-consecutive[-1]['time']!=timeframe:consecutive=[]
        consecutive.append(b)
    if consecutive and now-consecutive[-1]['time']-timeframe>timeframe:consecutive=[]
    values=[b['close'] for b in consecutive]
    result={'bars':len(values),'ema':None,'slope':None,'atr':None,'z':None,'change':None,'change_atr':None,'direction':'WARMUP'}
    if len(values)>=2:result['change']=values[-1]-values[-2]
    if len(values)>=21:
        result['ema']=ema(values);result['slope']=result['ema']-ema(values[:-1])
        result['direction']='UP' if result['slope']>0 else 'DOWN' if result['slope']<0 else 'FLAT'
    if len(values)>=window:
        recent=values[-window:];sd=statistics.pstdev(recent)
        result['z']=(recent[-1]-statistics.mean(recent))/sd if sd else None
    if len(values)>=15:
        ranges=[max(b['high']-b['low'],abs(b['high']-a['close']),abs(b['low']-a['close'])) for a,b in zip(consecutive,consecutive[1:])]
        atr=statistics.mean(ranges[:14])
        for r in ranges[14:]:atr=(atr*13+r)/14
        result['atr']=atr;result['change_atr']=result['change']/atr if atr else None
    return result


def scenario(prices,specs,lots,side,cost,margin=None):
    if side not in ('LONG','SHORT'):raise ValueError('Invalid side')
    na,fa,nx,fx=[number(p,'scenario fill',positive=True) for p in prices]
    wa,wb=[s['multiplier']*n for s,n in zip(specs,lots)]
    gross=(1 if side=='LONG' else -1)*((nx-na)*wa-(fx-fa)*wb)
    turnover=(na+nx)*wa+(fa+fx)*wb;fees=turnover*cost['rate']+sum(lots)*cost['other']
    if not all(math.isfinite(x) for x in (gross,turnover,fees)):raise ValueError('Scenario exceeds numerical range')
    net=gross-fees
    return {'gross':gross,'fees':fees,'net':net,'margin':margin,'return_pct':net/margin*100 if margin else None,
            'exposure':exposure(specs,lots)}
