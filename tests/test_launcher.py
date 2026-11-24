"""Exercise the documented one-command launcher through real process restarts."""
import http.client
import json
import os
from pathlib import Path
import queue
import re
import signal
import subprocess
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]

class LauncherTests(unittest.TestCase):
    def test_launch_register_stop_and_restart(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'launcher-fictional.db'
            process = None
            pin = None
            def start():
                nonlocal process,pin
                options = {'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session':True}
                process = subprocess.Popen([sys.executable,str(ROOT/'tools'/'launch.py'),'--data',str(path),'--port','0','--no-browser'],
                                           cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,**options)
                lines = queue.Queue()
                threading.Thread(target=lambda: lines.put(process.stdout.readline()),daemon=True).start()
                try:
                    first = lines.get(timeout=20)
                except queue.Empty:
                    self.fail('Launcher did not become ready within 20 seconds')
                match = re.search(r'http://127\.0\.0\.1:(\d+)',first)
                self.assertIsNotNone(match,first)
                pin_line=process.stdout.readline()
                pin=re.search(r'STAFF PIN: (\d{8})',pin_line).group(1)
                return int(match.group(1))
            def stop():
                if process is None: return
                if process.poll() is None:
                    process.send_signal(signal.CTRL_BREAK_EVENT if os.name == 'nt' else signal.SIGINT)
                    try: process.wait(timeout=5)
                    except subprocess.TimeoutExpired: process.kill(); process.wait(timeout=5)
                process.stdout.close()
            def call(port,body=None,token='',endpoint=None):
                c=http.client.HTTPConnection('127.0.0.1',port,timeout=5)
                c.request('POST' if body else 'GET',endpoint or ('/api/action' if body else '/api/session'),
                          json.dumps(body) if body else None,{'Content-Type':'application/json','X-Clinic-Token':token})
                r=c.getresponse(); payload=json.loads(r.read()); c.close()
                self.assertEqual(r.status,200,payload); return payload
            try:
                port=start(); token=call(port)['token']; token=call(port,{'pin':pin},token,'/api/login')['token']
                result=call(port,{'action':'register_checkin','name':'Launcher Fictional','age':32,'severity':2},token)
                self.assertEqual(result['state']['queue'][0]['severity'],2)
                stop()
                port=start(); token=call(port)['token']; token=call(port,{'pin':pin},token,'/api/login')['token']
                result=call(port,{'action':'state'},token)
                self.assertEqual(result['state']['queue'][0]['name'],'Launcher Fictional')
                self.assertEqual(result['state']['queue'][0]['severity'],2)
                self.assertFalse(result['state']['can_undo'])
            finally:
                stop()
