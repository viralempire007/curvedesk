"""Verify the packaged runtime serves bundled UI and writes private local data."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request

executable=Path(sys.argv[1]).resolve()
with socket.socket() as probe:
    probe.bind(('127.0.0.1',0));port=probe.getsockname()[1]
with tempfile.TemporaryDirectory() as directory:
    env={**os.environ,'CURVEDESK_DATA_DIR':directory,'CURVEDESK_PORT':str(port),'CURVEDESK_NO_BROWSER':'1'}
    process=subprocess.Popen([str(executable)],env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
    try:
        for _ in range(150):
            if process.poll() is not None:raise RuntimeError('Packaged process exited: '+process.communicate()[1].decode(errors='replace'))
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status',timeout=.5) as response:status=json.load(response)
                break
            except Exception:time.sleep(.1)
        else:raise RuntimeError('Packaged runtime did not become ready')
        assert status['mode']=='Research only' and status['order_calls']==0
        for resource,needle in [('/',b'CurveDesk'),('/app.js',b'loadReport'),('/style.css',b'--mint')]:
            with urllib.request.urlopen(f'http://127.0.0.1:{port}'+resource,timeout=3) as response:assert needle in response.read()
        assert (Path(directory)/'curvedesk.db').is_file()
        print('Packaged runtime smoke passed: server, bundled UI/assets, private data, zero order calls.')
    finally:
        process.terminate()
        try:process.communicate(timeout=5)
        except subprocess.TimeoutExpired:process.kill();process.communicate()
