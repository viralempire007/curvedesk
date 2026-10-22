"""Offline browser fixture. Synthetic inputs exist only in this test process."""
import json
import sys
import tempfile
import time
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from test_core import seeded,quote
from curvedesk.server import create_server

with tempfile.TemporaryDirectory() as directory:
    desk,pair=seeded(directory);now=time.time()
    # Two observations/minute demonstrate indicators without a real data subscription.
    for i in range(75):
        for offset in (0,30):
            stamp=int(now//60)*60-75*60+i*60+offset
            value=100+i*.05
            qs={'1':quote(value,value+1,stamp),'2':quote(120,121,stamp)}
            desk.dhan.rows=qs;desk.observe(qs,stamp)
    desk.dhan.rows={'1':quote(104,105,now),'2':quote(120,121,now)}
    http=create_server(desk,int(sys.argv[1]) if len(sys.argv)>1 else 8877)
    print('FIXTURE_READY',flush=True)
    try:http.serve_forever()
    finally:http.server_close()
