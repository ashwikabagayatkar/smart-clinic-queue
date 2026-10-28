import copy
import json
from pathlib import Path
import unittest
import uuid
import test_api
from test_triage import rule_answers
from assessment_store import atomic_write, encoded

class AssessmentTests(unittest.TestCase):
    setUp=test_api.ApiTests.setUp
    tearDown=test_api.ApiTests.tearDown
    start=test_api.ApiTests.start
    stop=test_api.ApiTests.stop
    http=test_api.ApiTests.http
    call=test_api.ApiTests.call
    register=test_api.ApiTests.register

    def public(self, endpoint, body, expected=200):
        status,result=self.http('POST','/api/patient/'+endpoint,body,{'X-Clinic-Token':self.public_token})
        self.assertEqual(status,expected,result);return result

    def submission(self,name='Patient Fictional',rule=-1):
        return {'submission_id':str(uuid.uuid4()),'identity':{'kind':'new','name':name,'age':30},
                'identity_confirmed':True,'answers':rule_answers(self.server.assessments.rules.data['rules'][rule])}

    def review(self,receipt,priority=4,reason='',expected=200):
        return self.call('review_assessment',reference=receipt['reference'],patient_id=receipt['patient_id'],priority=priority,
                         reviewer='Authorized Demo Staff',override_reason=reason,expected=expected)

    def test_patient_cannot_read_staff_data_or_queue(self):
        self.assertNotEqual(self.public_token,self.token)
        self.assertEqual(self.http('GET','/api/state',headers={'X-Clinic-Token':self.public_token})[0],403)
        self.assertEqual(self.http('POST','/api/action',{'action':'register','name':'No','age':20,'severity':1},headers={'X-Clinic-Token':self.public_token})[0],403)
        self.assertEqual(self.http('POST','/api/login',{'pin':'00000000' if self.server.staff_pin!='00000000' else '11111111'},headers={'X-Clinic-Token':self.public_token})[0],403)
        self.assertEqual(self.http('POST','/api/login',{'pin':'éééééééé'},headers={'X-Clinic-Token':self.public_token})[0],403)
        for action in ['register_pending','review_checkin','require_review']:
            self.call(action,expected=403)
        self.assertEqual(self.http('GET','/patient')[0],200)
        self.assertEqual(self.http('GET','/api/catalog')[1]['version'],'demo-2026-01')

    def test_new_patient_stays_unassigned_until_review(self):
        body=self.submission();receipt=self.public('submit',body)
        state=self.call('state')['state'];p=state['patients'][0]
        self.assertIsNone(p['severity']);self.assertEqual(p['status'],'Awaiting triage');self.assertEqual(state['queue'],[])
        self.assertIn('|none|5|',self.path.read_text(encoding="utf-8"))
        self.call('checkin',id=p['id'],severity=4,expected=409)
        result=self.review(receipt)
        self.assertEqual(result['state']['queue'][0]['severity'],4)
        a=result['assessments'][0];self.assertEqual(a['status'],'reviewed');self.assertEqual(a['review']['priority'],4)
        self.review(receipt,expected=409)
        self.assertEqual(len(self.call('state')['state']['queue']),1)

    def test_existing_identity_requires_bound_single_use_code(self):
        self.register('Existing A',4,'register');self.register('Existing B',4,'register')
        invitation=self.call('invite_patient',id='01')['invitation']
        identity={'kind':'existing','id':'1','code':invitation['code']}
        p=self.public('identify',identity)['identity'];self.assertEqual(p['name'],'Existing A')
        self.public('identify',{**identity,'id':'2'},400)
        self.public('identify',{**identity,'code':'wrong'},400)
        body=self.submission();body['identity']=identity
        receipt=self.public('submit',body);self.assertEqual(receipt['patient_id'],'1')
        data=self.call('state');self.assertEqual(len(data['state']['patients']),2)
        self.assertEqual(data['assessments'][0]['patient_name'],'Existing A')
        self.call('checkin',id='01',severity=2,expected=409)
        self.assertTrue(self.server.engine.call({'action':'state'})['state']['patients'][0]['needs_review'])
        self.assertFalse(self.server.engine.call({'action':'checkin','id':'1','severity':2})['ok'])
        self.public('identify',identity,400)
        self.assertEqual(self.public('submit',body)['reference'],receipt['reference'])
        body['submission_id']=str(uuid.uuid4());self.public('submit',body,400)
        metadata=self.server.assessments.path.read_text(encoding="utf-8");self.assertNotIn(invitation['code'],metadata)

    def test_idempotent_retries_and_conflicting_reuse(self):
        body=self.submission();first=self.public('submit',body)
        second=self.public('submit',body);self.assertEqual(first['reference'],second['reference'])
        self.assertEqual(len(self.call('state')['state']['patients']),1)
        changed=copy.deepcopy(body);changed['answers']['self_severity']='severe'
        self.public('submit',changed,409)
        self.stop();self.start()
        self.assertEqual(self.public('submit',body)['reference'],first['reference'])
        self.assertEqual(len(self.call('state')['assessments']),1)

    def test_incomplete_and_emergency_assessments_alert_staff(self):
        body=self.submission();body['answers']={'warnings':{'heavy_bleeding':'yes'}}
        receipt=self.public('submit',body);self.assertTrue(receipt['evaluation']['emergency'])
        self.assertIsNone(receipt['evaluation']['suggested_priority'])
        assessment=self.call('state')['assessments'][0]
        self.assertTrue(assessment['evaluation']['warning_flags']);self.assertEqual(assessment['status'],'pending')
        self.review(receipt,priority=1,expected=400)
        result=self.review(receipt,priority=1,reason='Staff assessed warning and arranged immediate care')
        self.assertEqual(result['state']['queue'][0]['severity'],1)
        self.assertTrue(result['assessments'][0]['review']['overridden'])

    def test_staff_override_reason_and_patient_association(self):
        receipt=self.public('submit',self.submission())
        self.review(receipt,priority=2,expected=400)
        self.review(receipt,priority=0,reason='Invalid',expected=400)
        wrong={**receipt,'patient_id':'999'};self.review(wrong,expected=400)
        result=self.review(receipt,priority=2,reason='Staff found concerns not represented by the demonstration rule')
        assessment=result['assessments'][0]
        self.assertEqual(assessment['evaluation']['suggested_priority'],4)
        self.assertEqual(assessment['review']['priority'],2)
        self.assertTrue(assessment['review']['overridden'])

    def test_c_heap_fairness_uses_staff_review_arrival_order(self):
        a=self.public('submit',self.submission('First Fictional'));b=self.public('submit',self.submission('Second Fictional'))
        c=self.public('submit',self.submission('Third Fictional'))
        self.review(b,2,'Staff choice');self.review(a,2,'Staff choice');data=self.review(c,1,'Staff choice')
        self.assertEqual([p['id'] for p in data['state']['queue']],['3','2','1'])
        self.assertEqual([p['order'] for p in data['state']['queue']],['3','1','2'])
        self.stop();self.start()
        self.assertEqual([p['id'] for p in self.call('state')['state']['queue']],['3','2','1'])

    def test_c_fifo_and_undo_restore_explicit_unassigned_state(self):
        a=self.public('submit',self.submission('First Fictional'));b=self.public('submit',self.submission('Second Fictional'))
        self.review(b);result=self.review(a)
        self.assertEqual([p['id'] for p in result['state']['queue']],['2','1'])
        result=self.call('undo')
        self.assertIsNone(result['state']['patients'][0]['severity'])
        self.assertEqual(result['state']['patients'][0]['status'],'Awaiting triage')
        self.assertEqual(result['assessments'][0]['status'],'reviewed') # Historical staff decision is not erased.

    def test_sidecar_save_failure_rolls_back_new_patient_and_review(self):
        blocker=Path(str(self.server.assessments.path)+'.tmp');blocker.write_text('preserve')
        body=self.submission();self.public('submit',body,500)
        self.assertEqual(self.call('state')['state']['patients'],[])
        self.assertFalse(self.server.assessments.journal.exists());self.assertEqual(blocker.read_text(encoding="utf-8"),'preserve')
        blocker.unlink();receipt=self.public('submit',body)
        before=self.call('state')['state'];blocker.write_text('preserve')
        self.review(receipt,expected=500)
        result=self.call('state');self.assertEqual(result['state'],before);self.assertEqual(result['assessments'][0]['status'],'pending')
        blocker.unlink();self.review(receipt)

    def test_prepared_crash_journal_recovers_both_files_on_restart(self):
        store=self.server.assessments
        old_core=self.path.read_bytes();old_meta=store.path.read_bytes()
        journal={'version':1,'clinic_before':encoded(old_core),'assessments_before':encoded(old_meta)}
        atomic_write(store.journal,json.dumps(journal).encode())
        self.server.engine.call({'action':'register_pending','name':'Interrupted Fictional','age':25})
        atomic_write(store.path,b'{"interrupted":true}')
        self.stop();self.start()
        self.assertEqual(self.path.read_bytes(),old_core);self.assertEqual(self.server.assessments.path.read_bytes(),old_meta)
        self.assertFalse(self.server.assessments.journal.exists())
        self.assertEqual(self.call('state')['state']['patients'],[])

    def test_assessments_and_review_reloaded_with_correct_patient(self):
        first=self.public('submit',self.submission('Pending Fictional'))
        second=self.public('submit',self.submission('Reviewed Fictional'))
        self.review(second,2,'Staff override')
        self.stop();self.start()
        records=self.call('state')['assessments']
        self.assertEqual([a['patient_id'] for a in records],['1','2'])
        self.assertEqual([a['status'] for a in records],['pending','reviewed'])
        self.assertEqual(records[1]['review']['override_reason'],'Staff override')
        self.assertEqual(records[0]['reference'],first['reference'])

    def test_existing_submission_rollback_preserves_code_and_c_gate(self):
        self.register('Existing Rollback Fictional',4,'register')
        invitation=self.call('invite_patient',id='1')['invitation']
        body=self.submission();body['identity']={'kind':'existing','id':'1','code':invitation['code']}
        blocker=Path(str(self.server.assessments.path)+'.tmp');blocker.write_text('preserve')
        self.public('submit',body,500)
        self.assertFalse(self.call('state')['state']['patients'][0]['needs_review'])
        blocker.unlink();self.public('identify',body['identity'])
        self.public('submit',body)
        self.assertTrue(self.call('state')['state']['patients'][0]['needs_review'])

    def test_replacement_and_expired_intake_codes(self):
        self.register('Existing Code Fictional',4,'register')
        first=self.call('invite_patient',id='1')['invitation'];second=self.call('invite_patient',id='1')['invitation']
        self.public('identify',{'kind':'existing','id':'1','code':first['code']},400)
        self.public('identify',{'kind':'existing','id':'1','code':second['code']})
        import hashlib
        key=hashlib.sha256(second['code'].encode()).hexdigest()
        self.server.assessments.data['invitations'][key]['expires']=0
        self.public('identify',{'kind':'existing','id':'1','code':second['code']},400)

    def test_corrupt_association_is_rejected_without_reset(self):
        receipt=self.public('submit',self.submission('Correct Identity Fictional'))
        data=json.loads(self.server.assessments.path.read_text(encoding="utf-8"))
        data['assessments'][0]['patient_name']='Different Identity Fictional'
        self.server.assessments.path.write_text(json.dumps(data))
        self.call('load',expected=400)
        result=self.call('state')
        self.assertEqual(result['assessments'][0]['patient_name'],'Correct Identity Fictional')
        self.assertEqual(result['assessments'][0]['reference'],receipt['reference'])
        self.assertEqual(json.loads(self.server.assessments.path.read_text(encoding="utf-8"))['assessments'][0]['patient_name'],'Different Identity Fictional')

    def test_staff_pin_attempts_rate_limited_without_patient_data(self):
        wrong='00000000' if self.server.staff_pin!='00000000' else '11111111'
        for _ in range(10):
            self.assertEqual(self.http('POST','/api/login',{'pin':wrong},headers={'X-Clinic-Token':self.public_token})[0],403)
        self.assertEqual(self.http('POST','/api/login',{'pin':wrong},headers={'X-Clinic-Token':self.public_token})[0],429)
        self.assertEqual(self.http('GET','/api/state',headers={'X-Clinic-Token':self.public_token})[0],403)

    def test_unicode_paths_assessment_review_and_restart(self):
        self.stop()
        folder=Path(self.temp.name)/'Clinic records café 演示';folder.mkdir()
        self.path=folder/'patient records.db';self.start()
        body=self.submission('Zoë Fictional');body['answers']['additional']='Fictional note: symptômes / 症状'
        receipt=self.public('submit',body)
        self.assertIsNone(receipt['evaluation']['suggested_priority'])
        self.review(receipt,2,'Staff reviewed the fictional notes')
        self.stop();self.start()
        result=self.call('state')
        self.assertEqual(result['state']['queue'][0]['name'],'Zoë Fictional')
        self.assertEqual(result['state']['queue'][0]['severity'],2)
        self.assertEqual(result['assessments'][0]['answers']['additional'],'Fictional note: symptômes / 症状')
        self.assertEqual(result['assessments'][0]['review']['priority'],2)

    def test_local_port_cannot_be_shared_by_second_database(self):
        from server import create_server
        with self.assertRaises(OSError): create_server(Path(self.temp.name)/'second.db',port=self.port)

    def test_invalid_submission_does_not_create_patient(self):
        body=self.submission();body['identity_confirmed']=False;self.public('submit',body,400)
        body=self.submission();body['answers']['symptoms']=['invented'];self.public('submit',body,400)
        body=self.submission();body['identity']['id']='99';self.public('submit',body,400)
        self.assertEqual(self.call('state')['state']['patients'],[])
