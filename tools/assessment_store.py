"""Assessment metadata alongside the C snapshot, with a recoverable cross-file journal."""
import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import secrets
import time
import uuid
from triage import RuleEngine

class Conflict(RuntimeError):
    pass


def sync_parent(path):
    if os.name != 'nt':
        try:
            fd=os.open(str(Path(path).parent), os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        except OSError:
            pass  # Filesystem-dependent power-loss durability is not promised.


def atomic_write(path, data):
    path=Path(path); temp=Path(str(path)+'.tmp'); owned=False
    try:
        with temp.open('xb') as f:
            owned=True; f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(temp,path); sync_parent(path)
    finally:
        if owned and temp.exists(): temp.unlink()


def encoded(data):
    return {'data':base64.b64encode(data).decode('ascii'),'sha256':hashlib.sha256(data).hexdigest()}


def restore_image(path, image):
    data=base64.b64decode(image['data'],validate=True)
    if hashlib.sha256(data).hexdigest()!=image['sha256']: raise ValueError('Journal checksum mismatch.')
    if not Path(path).exists() or Path(path).read_bytes()!=data: atomic_write(path,data)


def recover(path):
    journal=Path(str(path)+'.intake-journal.json')
    if not journal.exists(): return
    record=json.loads(journal.read_text(encoding='utf-8'))
    if record.get('version')!=1: raise RuntimeError('Unsupported assessment recovery journal. Preserve all files for recovery.')
    # No paths are accepted from a journal. Both destinations derive from the locked database.
    restore_image(path,record['clinic_before'])
    restore_image(str(path)+'.assessments.json',record['assessments_before'])
    journal.unlink(); sync_parent(path)


class AssessmentStore:
    def __init__(self, engine):
        self.engine=engine; self.rules=RuleEngine(); self.blocked=False
        self.path=Path(str(engine.path)+'.assessments.json')
        self.journal=Path(str(engine.path)+'.intake-journal.json')
        if not self.path.exists(): atomic_write(self.path,b'{"version":1,"assessments":[],"invitations":{}}\n')
        self.reload()

    def reload(self):
        try: self._reload()
        except (ValueError,KeyError,TypeError,AttributeError):
            raise ValueError('Invalid assessment store or patient association. It was not reset.') from None

    def _reload(self):
        data=json.loads(self.path.read_text(encoding='utf-8'))
        if set(data)!={'version','assessments','invitations'} or data['version']!=1 or not isinstance(data['assessments'],list) or not isinstance(data['invitations'],dict):
            raise ValueError('Invalid assessment store. It was not reset.')
        patients={p['id']:p for p in self.engine.call({'action':'state'})['state']['patients']}
        refs=set(); submissions=set(); pending=set()
        for a in data['assessments']:
            if (a['reference'] in refs or a['submission_id'] in submissions or a['patient_id'] not in patients
                    or a['patient_name']!=patients[a['patient_id']]['name'] or a['patient_age']!=patients[a['patient_id']]['age']
                    or a['status'] not in ('pending','reviewed') or a['evaluation']['suggested_priority'] not in (None,1,2,3,4)):
                raise ValueError('Invalid patient-to-assessment association or duplicate assessment.')
            self.rules.validate(a['answers'])
            if a['status']=='pending':
                if a['patient_id'] in pending: raise ValueError('Duplicate pending assessments.')
                if not patients[a['patient_id']]['needs_review']: raise ValueError('Pending assessment is not gated in the C patient record.')
                pending.add(a['patient_id'])
            elif not a['review'] or type(a['review']['priority']) is not int or a['review']['priority'] not in (1,2,3,4):
                raise ValueError('Invalid staff review.')
            refs.add(a['reference']); submissions.add(a['submission_id'])
        for invitation in data['invitations'].values():
            if invitation['patient_id'] not in patients: raise ValueError('Invitation refers to a missing patient.')
        self.data=data

    def transaction(self, operation):
        if self.blocked: raise RuntimeError('Recovery required. Stop the application and repair storage before restarting.')
        before=copy.deepcopy(self.data)
        checkpoint=self.engine.lib.app_checkpoint(self.engine.handle)
        if not checkpoint: raise RuntimeError('Not enough memory. Nothing changed.')
        prepared=False
        try:
            if self.journal.exists(): raise RuntimeError('Unfinished recovery journal; restart to recover before continuing.')
            record={'version':1,'clinic_before':encoded(self.engine.path.read_bytes()),'assessments_before':encoded(self.path.read_bytes())}
            atomic_write(self.journal,json.dumps(record).encode()); prepared=True
            result=operation()
            atomic_write(self.path,json.dumps(self.data,ensure_ascii=False,indent=2).encode('utf-8')+b'\n')
            self.journal.unlink(); sync_parent(self.path)
        except BaseException:
            self.data=before
            self.engine.lib.app_restore_checkpoint(self.engine.handle,checkpoint); checkpoint=None
            if prepared:
                try: recover(self.engine.path)
                except Exception:
                    self.blocked=True
                    raise RuntimeError('Storage rollback could not finish. Journal retained; stop and restart after fixing storage.') from None
            raise
        finally:
            if checkpoint: self.engine.lib.app_discard_checkpoint(checkpoint)
        return result

    def patient(self, ident):
        if not isinstance(ident,str) or not ident.isascii() or not ident.isdigit() or not 1<=int(ident)<2**64:
            raise ValueError('Patient ID must be a positive decimal string.')
        matches=self.engine.call({'action':'find_id','id':ident})['matches']
        if not matches: raise ValueError('Patient not found.')
        return matches[0]

    def has_pending(self, ident):
        if isinstance(ident,str) and ident.isascii() and ident.isdigit(): ident=str(int(ident))
        return any(a['patient_id']==ident and a['status']=='pending' for a in self.data['assessments'])

    def invite(self, ident):
        p=self.patient(ident); ident=p['id']
        if p['status'] in ('Waiting','Consulting') or self.has_pending(ident): raise Conflict('Patient is already waiting, consulting or has an assessment awaiting review.')
        code=secrets.token_urlsafe(24); hashed=hashlib.sha256(code.encode()).hexdigest()
        def apply():
            self.data['invitations']={k:v for k,v in self.data['invitations'].items() if v['patient_id']!=ident or v.get('used_reference')}
            self.data['invitations'][hashed]={'patient_id':ident,'expires':int(time.time())+86400,'used_reference':None}
            return {'patient_id':ident,'name':p['name'],'code':code}
        return self.transaction(apply)

    def identify(self, identity):
        if not isinstance(identity,dict) or identity.get('kind') not in ('existing','new'): raise ValueError('Choose existing patient or new patient.')
        if identity['kind']=='existing':
            if set(identity)!={'kind','id','code'} or not isinstance(identity['code'],str): raise ValueError('Enter your patient ID and staff-issued intake code.')
            key=hashlib.sha256(identity['code'].encode()).hexdigest()
            invitation=self.data['invitations'].get(key)
            if (not invitation or invitation['patient_id']!=identity['id'] or invitation['expires']<time.time() or invitation['used_reference']):
                raise ValueError('Patient ID and intake code do not match, or the code has expired/been used. Ask staff for a new code.')
            p=self.patient(identity['id'])
            if p['status'] in ('Waiting','Consulting'): raise Conflict('You are already in the care queue. Tell clinic staff directly about new symptoms.')
            return {'id':p['id'],'name':p['name'],'age':p['age']}
        if set(identity)!={'kind','name','age'}: raise ValueError('Enter only your name and age for new registration.')
        # Reuse the backend's C-compatible input rules, without creating any record yet.
        name=identity['name']; age=identity['age']
        if (not isinstance(name,str) or not name.strip() or len(name.encode('utf-8'))>79 or any(ord(c)<32 or ord(c)==127 or c=='|' for c in name)
                or type(age) is not int or not 0<=age<=150): raise ValueError('Enter a valid name (at most 79 UTF-8 bytes) and age (0–150).')
        return {'id':None,'name':name,'age':age}

    def submit(self, body):
        if not isinstance(body,dict) or set(body)!={'submission_id','identity','identity_confirmed','answers'} or body['identity_confirmed'] is not True:
            raise ValueError('Review and confirm that these answers belong to you before submitting.')
        try:
            if str(uuid.UUID(body['submission_id']))!=body['submission_id']: raise ValueError()
        except (ValueError,AttributeError,TypeError): raise ValueError('A valid submission reference is required.') from None
        digest=hashlib.sha256(json.dumps(body,sort_keys=True,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()
        for a in self.data['assessments']:
            if a['submission_id']==body['submission_id']:
                if not secrets.compare_digest(a['payload_digest'],digest): raise Conflict('This submission reference has already been used for different answers.')
                return self.receipt(a)
        p=self.identify(body['identity']); answers=self.rules.validate(body['answers']); evaluation=self.rules.evaluate(answers)
        if p['id'] and self.has_pending(p['id']): raise Conflict('Your assessment is already awaiting staff review. Tell staff if your symptoms change.')
        def apply():
            if p['id'] is None:
                result=self.engine.call({'action':'register_pending','name':p['name'],'age':p['age']})
                if not result['ok']: raise Conflict(result['message'])
                p['id']=str(int(result['state']['next_id'])-1)
            else:
                result=self.engine.call({'action':'require_review','id':p['id']})
                if not result['ok']: raise Conflict(result['message'])
            a={'reference':'AS-'+uuid.uuid4().hex[:16].upper(),'submission_id':body['submission_id'],'payload_digest':digest,
               'patient_id':p['id'],'patient_name':p['name'],'patient_age':p['age'],'answers':answers,'evaluation':evaluation,
               'submitted_at':int(time.time()),'status':'pending','review':None}
            self.data['assessments'].append(a)
            if body['identity']['kind']=='existing':
                key=hashlib.sha256(body['identity']['code'].encode()).hexdigest(); self.data['invitations'][key]['used_reference']=a['reference']
            return self.receipt(a)
        return self.transaction(apply)

    @staticmethod
    def receipt(a):
        return {'reference':a['reference'],'patient_id':a['patient_id'],'evaluation':a['evaluation'],'status':a['status'],
                'message':'Assessment saved. Staff must review it before you can join the consultation queue.' if a['status']=='pending' else 'This assessment has already been reviewed. Ask clinic staff about your current care status.'}

    def review(self, body):
        if set(body)!={'action','reference','patient_id','priority','reviewer','override_reason'}: raise ValueError('Invalid review fields.')
        priority=body['priority']; reviewer=body['reviewer']; reason=body['override_reason']
        if type(priority) is not int or priority not in (1,2,3,4): raise ValueError('Staff-confirmed priority must be 1–4.')
        if not isinstance(reviewer,str) or not reviewer.strip() or len(reviewer)>80 or any(ord(c)<32 for c in reviewer): raise ValueError('Enter the reviewing staff member name (at most 80 characters).')
        if not isinstance(reason,str) or len(reason)>500: raise ValueError('Override reason must be text of at most 500 characters.')
        a=next((a for a in self.data['assessments'] if a['reference']==body['reference']),None)
        if not a or a['patient_id']!=body['patient_id']: raise ValueError('Assessment reference and patient ID do not match.')
        if a['status']!='pending': raise Conflict('Assessment already reviewed. It cannot enqueue the patient twice.')
        if priority!=a['evaluation']['suggested_priority'] and not reason.strip():
            raise ValueError('Explain the staff decision when overriding a suggestion or assigning priority without a matching rule.')
        def apply():
            result=self.engine.call({'action':'review_checkin','id':a['patient_id'],'severity':priority})
            if not result['ok']: raise Conflict(result['message'])
            p=next(p for p in result['state']['patients'] if p['id']==a['patient_id'])
            a['status']='reviewed'; a['review']={'priority':priority,'reviewer':reviewer.strip(),'override_reason':reason.strip(),
                'reviewed_at':int(time.time()),'queue_order':p['order'],'overridden':priority!=a['evaluation']['suggested_priority']}
            return result
        return self.transaction(apply)

    def public_records(self):
        return [{k:v for k,v in a.items() if k not in ('submission_id','payload_digest')} for a in self.data['assessments']]
