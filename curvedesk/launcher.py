"""Cross-platform desktop entry, packaged with its own Python runtime."""
import json
import logging
import os
import sys
import threading
import time
import http.client
import webbrowser
from curvedesk.storage import default_directory
from curvedesk.server import main


def main_desktop():
    directory=default_directory();directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    logging.basicConfig(filename=directory/'launcher.log',level=logging.INFO)
    port=int(os.environ.get('CURVEDESK_PORT','8876'));url=f'http://127.0.0.1:{port}'
    def healthy():
        connection=http.client.HTTPConnection('127.0.0.1',port,timeout=1)
        try:
            connection.request('GET','/api/status')
            response=connection.getresponse()
            return response.status==200 and json.loads(response.read(100000)).get('mode')=='Research only'
        except Exception:return False
        finally:connection.close()
    if healthy():
        if os.environ.get('CURVEDESK_NO_BROWSER')!='1':webbrowser.open(url)
        return
    def open_ready():
        for _ in range(100):
            if healthy():
                if os.environ.get('CURVEDESK_NO_BROWSER')!='1':webbrowser.open(url)
                return
            time.sleep(.2)
    threading.Thread(target=open_ready,daemon=True).start()
    try:main()
    except Exception:
        logging.exception('CurveDesk failed to start')
        try:
            import tkinter.messagebox
            tkinter.messagebox.showerror('CurveDesk','Unable to start. Port '+str(port)+' may be in use. See '+str(directory/'launcher.log'))
        except Exception:pass
        raise


if __name__=='__main__':main_desktop()
