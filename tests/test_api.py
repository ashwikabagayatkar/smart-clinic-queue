"""Real HTTP → Python transport → C core integration, using temporary fictional data."""
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from server import create_server


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'fictional.db'
        self.start()

    def start(self):
        self.server = create_server(self.path, port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.port = self.server.server_port
        status, session = self.http('GET', '/api/session')
        self.assertEqual(status, 200)
        self.public_token = session['token']
        self.token = session['token']
        code,login=self.http('POST','/api/login',{'pin':self.server.staff_pin})
        self.assertEqual(code,200)
        self.token=login['token']

    def stop(self):
        self.server.shutdown(); self.thread.join(timeout=5)
        self.server.server_close(); self.server.engine.close()

    def tearDown(self):
        self.stop(); self.temp.cleanup()

    def http(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.port, timeout=5)
        h = {'Content-Type': 'application/json', 'X-Clinic-Token': getattr(self, 'token', '')}
        h.update(headers or {})
        raw = json.dumps(body) if body is not None else None
        conn.request(method, path, raw, h)
        response = conn.getresponse()
        status, content_type, payload = response.status, response.getheader('Content-Type'), response.read()
        conn.close()
        return status, json.loads(payload) if content_type.startswith('application/json') else payload

    def call(self, action, expected=200, **fields):
        code, result = self.http('POST', '/api/action', {'action':action, **fields})
        self.assertEqual(code, expected, result)
        return result

    def register(self, name, severity, action='register_checkin'):
        return self.call(action, name=name, age=30, severity=severity)

    def test_severity_is_required_validated_stored_and_persisted(self):
        for severity in [None, 0, 5, -1, 1.5, True, '2']:
            self.call('register', expected=400, name='Invalid Fictional', age=30, severity=severity)
        self.call('register', expected=400, name='Missing Fictional', age=30)
        for value in range(1, 5):
            data = self.register(f'Fictional {value}', value, 'register')
            self.assertEqual(data['state']['patients'][-1]['severity'], value)
        self.stop(); self.start()
        patients = self.call('state')['state']['patients']
        self.assertEqual([p['severity'] for p in patients], [1, 2, 3, 4])
        self.assertEqual(self.call('register', name='Next Fictional', age=0, severity=4)['state']['next_id'], '6')

    def test_heap_ties_and_fifo_are_c_ordered(self):
        for name, severity in [('Normal A',4),('Urgent A',2),('Critical A',1),('Critical B',1),('Normal B',4),('Priority A',3)]:
            self.register(name, severity)
        state = self.call('state')['state']
        self.assertEqual([p['id'] for p in state['queue']], ['3','4','2','6','1','5'])
        self.assertEqual([p['wait'] for p in state['queue']], [0,15,30,45,60,75])
        for ident in ['3','4','2','6','1','5']:
            self.assertEqual(self.call('next')['state']['active']['id'], ident)
            self.call('complete')
        self.call('next', expected=409)
        self.assertEqual(self.call('state')['state']['stats']['completed'], 6)

    def test_active_queue_and_history_survive_restart(self):
        self.register('Normal Fictional',4); self.register('Critical Fictional',1)
        self.call('next'); self.stop(); self.start()
        state = self.call('state')['state']
        self.assertEqual(state['active']['id'], '2'); self.assertFalse(state['can_undo'])
        self.call('next', expected=409); self.call('complete'); self.call('no_show', id='1')
        self.stop(); self.start()
        state = self.call('state')['state']
        self.assertEqual([v['outcome'] for v in state['history']], ['Completed','No-show'])
        self.assertEqual(state['stats']['waiting'], 0)

    def test_undo_latest_eligible_and_invalid_transitions(self):
        self.register('Normal Fictional',4); self.register('Critical Fictional',1)
        self.call('next')  # top undo is now ineligible; undo finds the still-waiting normal patient
        state = self.call('undo')['state']
        self.assertEqual(state['patients'][0]['status'], 'Registered')
        self.assertEqual(state['patients'][0]['severity'], 4)
        self.assertEqual(state['active']['id'], '2')
        self.call('undo', expected=409)
        self.call('checkin', id='2', severity=2, expected=409)
        self.call('no_show', id='2', expected=409)
        self.call('complete'); self.call('complete', expected=409)
        self.assertEqual(len(self.call('state')['state']['history']), 1)

    def test_hash_bst_exact_search_duplicates_and_escaping(self):
        self.register('Fictional "Quoted" \\ Name',2)
        self.register('Duplicate Fictional',4); self.register('Duplicate Fictional',1)
        data = self.call('find_name', name='Duplicate Fictional')
        self.assertEqual(len(data['matches']), 2)
        self.assertEqual(self.call('find_name', name='duplicate fictional')['matches'], [])
        self.assertEqual(self.call('find_id', id='1')['matches'][0]['name'], 'Fictional "Quoted" \\ Name')
        self.assertEqual(self.call('find_id', id='999')['matches'], [])
        self.call('checkin', id='999', severity=2, expected=409)
        for ident in ['0','-1','18446744073709551616',1,True]:
            self.call('find_id', id=ident, expected=400)
        self.call('register', id='1', name='No Duplicate ID', age=30, severity=2, expected=400)

    def test_both_report_algorithms_use_stored_severity(self):
        self.register('Zed Fictional',4, 'register'); self.register('Alpha Fictional',1, 'register')
        self.register('Middle Fictional',2, 'register')
        for algorithm in [1,2]:
            for key, expected in [(0,['2','3','1']),(1,['1','2','3']),(2,['2','3','1'])]:
                rows = self.call('report', key=key, algorithm=algorithm)['state']['patients']
                self.assertEqual([p['id'] for p in rows], expected)
        self.call('report', key=4, algorithm=1, expected=400)
        self.call('report', key=0, algorithm=0, expected=400)

    def test_save_failure_rolls_back_registration_queue_and_undo(self):
        self.register('Existing Fictional',2)
        before = self.call('state')['state']
        temp = Path(str(self.path)+'.tmp'); temp.write_text('do not overwrite')
        data = self.register_failure('Rolled Back Fictional')
        self.assertIn('rolled back',data['message'])
        self.assertEqual(data['state'], before)
        self.assertEqual(temp.read_text(encoding="utf-8"), 'do not overwrite')
        self.call('undo', expected=409)
        self.assertEqual(self.call('state')['state'], before)
        temp.unlink()
        self.call('undo')
        self.stop(); self.start()
        self.assertEqual(len(self.call('state')['state']['patients']), 1)

    def register_failure(self, name):
        return self.call('register_checkin', name=name, age=30, severity=1, expected=409)

    def test_load_failure_keeps_state_and_does_not_overwrite(self):
        self.register('Existing Fictional',2)
        before = self.call('state')['state']
        self.path.write_text('bad snapshot')
        self.call('load', expected=409)
        self.assertEqual(self.call('state')['state'], before)
        self.assertEqual(self.path.read_text(encoding="utf-8"), 'bad snapshot')
        self.call('save')
        self.call('load')
        self.assertFalse(self.call('state')['state']['can_undo'])

    def test_all_mutation_failures_preserve_state_and_disk(self):
        self.register('Fictional Normal', 4)
        original = self.path.read_bytes()
        blocker = Path(str(self.path) + '.tmp')
        blocker.write_text('do not replace')
        before = self.call('state')['state']
        for action, args in [('next', {}), ('no_show', {'id':'1'})]:
            self.call(action, expected=409, **args)
            self.assertEqual(self.call('state')['state'], before)
            self.assertEqual(self.path.read_bytes(), original)
        blocker.unlink()
        self.call('next')
        before = self.call('state')['state']; original = self.path.read_bytes()
        blocker.write_text('do not replace')
        self.call('complete', expected=409)
        self.assertEqual(self.call('state')['state'], before)
        self.assertEqual(self.path.read_bytes(), original)
        blocker.unlink()

    def test_input_validation(self):
        for name in ['', '   ', 'A|B', 'A\nB', '\0', 'X'*80, 'é'*40]:
            self.call('register', name=name, age=30, severity=2, expected=400)
        for age in [-1,151,None,True,2.5,'30']:
            self.call('register', name='Fictional', age=age, severity=2, expected=400)
        self.register('X'*79,3)
        code, _ = self.http('POST','/api/action', {'action':[]}); self.assertEqual(code,400)
        self.assertEqual(len(self.call('state')['state']['patients']),1)

    def test_local_security_and_assets(self):
        self.assertEqual(self.http('GET','/api/state',headers={'X-Clinic-Token':''})[0],403)
        self.assertEqual(self.http('GET','/api/session',headers={'Host':'attacker.example'})[0],403)
        self.assertEqual(self.http('GET','/api/session',headers={'Origin':'https://attacker.example'})[0],403)
        self.assertEqual(self.http('GET','/api/session',headers={'Sec-Fetch-Site':'cross-site'})[0],403)
        self.assertEqual(self.http('POST','/api/action',{'action':'save'},headers={'Origin':'https://attacker.example'})[0],403)
        for path in ['/','/style.css','/app.js']:
            self.assertEqual(self.http('GET',path)[0],200)
        for path in ['/clinic.db','/../clinic.db','/tools/server.py','/.env']:
            self.assertEqual(self.http('GET',path)[0],404)

    def test_second_server_cannot_open_same_data(self):
        with self.assertRaisesRegex(RuntimeError,'already open'):
            create_server(self.path, port=0)

    def test_legacy_zero_severity_is_rejected_without_reset(self):
        self.path.write_text('CLINIC1|2|1\nP|1|Legacy Fictional|30|0|0|0|0\nEND\n')
        before = self.path.read_bytes()
        self.call('load',expected=409)
        self.assertEqual(self.path.read_bytes(),before)


class LegacyRepairTests(unittest.TestCase):
    def test_staff_assignment_and_backup(self):
        from repair_severity import repair
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'legacy.db'
            original = 'CLINIC1|2|1\nP|1|Legacy Fictional|30|0|0|0|0\nEND\n'
            path.write_text(original)
            choices = iter(['', '0', '5', '2'])
            repair(path, lambda _: next(choices))
            self.assertEqual(Path(str(path)+'.before-triage.bak').read_text(encoding="utf-8"), original)
            from server import Engine
            engine = Engine(path)
            try:
                self.assertEqual(engine.call({'action':'state'})['state']['patients'][0]['severity'],2)
            finally:
                engine.close()


if __name__ == '__main__':
    unittest.main()
