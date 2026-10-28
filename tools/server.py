"""Loopback-only HTTP/ctypes transport. All clinic operations and sorting run in C."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import secrets
import shutil
import socket
import sys
import time
from assessment_store import AssessmentStore, Conflict, recover
from http.server import BaseHTTPRequestHandler, HTTPServer
import webbrowser

ROOT = Path(__file__).resolve().parent.parent
def safe_token(value, expected):
    return isinstance(value,str) and value.isascii() and secrets.compare_digest(value,expected)


ACTIONS = {'state': 0, 'register': 1, 'checkin': 2, 'next': 3, 'complete': 4,
           'no_show': 5, 'undo': 6, 'save': 7, 'load': 8, 'find_id': 9,
           'find_name': 10, 'report': 11, 'register_checkin': 12, 'register_pending':13, 'review_checkin':14, 'require_review':15, 'reprioritize':16}


def integer(value, label, low, high):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{label} must be an integer from {low} to {high}.')
    return value


def patient_id(value):
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        raise ValueError('Patient ID must be a positive decimal string.')
    result = int(value)
    if not 1 <= result < 2**64:
        raise ValueError('Patient ID is outside the valid range.')
    return result


def name_value(value):
    if not isinstance(value, str) or not value.strip() or len(value.encode('utf-8')) > 79:
        raise ValueError('Name is required and must be at most 79 UTF-8 bytes.')
    if any(ord(c) < 32 or ord(c) == 127 or c == '|' for c in value):
        raise ValueError('Names cannot contain control characters or |.')
    return value


class DataLock:
    """OS lock is released on crashes; the sidecar file is intentionally retained."""
    def __init__(self, path):
        self.file = open(str(path) + '.lock', 'a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.file.seek(0, 2)
                if not self.file.tell():
                    self.file.write(b'0'); self.file.flush()
                self.file.seek(0)
                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.file.close()
            raise RuntimeError('This database is already open in another web server.') from None

    def close(self):
        self.file.close()


class Engine:
    def __init__(self, path, library=None):
        self.path = Path(path).resolve()
        self.lock = DataLock(self.path)
        self.handle = None
        self.dll_directories = []
        try:
            recover(self.path)
            if not self.path.exists():
                with self.path.open('x', encoding='ascii', newline='\n') as f:
                    f.write('CLINIC1|1|1\nEND\n'); f.flush(); os.fsync(f.fileno())
            ext = 'dll' if os.name == 'nt' else 'so'
            library_path=Path(library or ROOT/'build'/f'clinic_core.{ext}').resolve()
            if os.name=='nt':
                # Python 3.8+ does not search PATH for dependent DLLs by default.
                folders={library_path.parent}
                compiler=shutil.which(os.environ.get('CC','gcc'))
                if compiler: folders.add(Path(compiler).resolve().parent)
                for folder in folders:
                    self.dll_directories.append(os.add_dll_directory(str(folder)))
            try:
                self.lib = ctypes.CDLL(str(library_path))
            except OSError as error:
                raise RuntimeError('Cannot load the C library. Match Python/GCC architectures, keep MinGW bin on PATH, and rebuild after stopping all servers. '+str(error)) from None
            self.lib.app_open.argtypes = [ctypes.c_char_p]
            self.lib.app_open.restype = ctypes.c_void_p
            self.lib.app_close.argtypes = [ctypes.c_void_p]
            self.lib.app_close.restype = None
            self.lib.app_release.argtypes = [ctypes.c_void_p]
            self.lib.app_release.restype = None
            self.lib.app_call.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_char_p,
                                         ctypes.c_uint64, ctypes.c_uint, ctypes.c_uint,
                                         ctypes.c_uint, ctypes.c_uint]
            self.lib.app_call.restype = ctypes.c_void_p
            self.lib.app_checkpoint.argtypes = [ctypes.c_void_p]
            self.lib.app_checkpoint.restype = ctypes.c_void_p
            self.lib.app_restore_checkpoint.argtypes = [ctypes.c_void_p,ctypes.c_void_p]
            self.lib.app_restore_checkpoint.restype = None
            self.lib.app_discard_checkpoint.argtypes = [ctypes.c_void_p]
            self.lib.app_discard_checkpoint.restype = None
            self.handle = self.lib.app_open(str(self.path).encode('utf-8'))
            if not self.handle:
                raise RuntimeError('Cannot load the database. It was not overwritten. Check its format, '
                                   'permissions, and staff-assigned severity (legacy severity 0 is rejected).')
        except Exception:
            self.lock.close()
            for directory in self.dll_directories: directory.close()
            self.dll_directories.clear()
            raise

    def close(self):
        if self.handle:
            self.lib.app_close(self.handle); self.handle = None
        self.lock.close()
        for directory in self.dll_directories: directory.close()
        self.dll_directories.clear()

    def call(self, body):
        if not isinstance(body, dict) or not isinstance(body.get('action'), str) or body['action'] not in ACTIONS:
            raise ValueError('Choose a valid action.')
        action = body['action']
        allowed = {'action'}
        name, ident, age, severity, key, algorithm = '', 0, 0, 0, 0, 1
        if action in {'register', 'register_checkin','register_pending'}:
            allowed |= {'name', 'age'} | ({'severity'} if action!='register_pending' else set())
            name = name_value(body.get('name'))
            age = integer(body.get('age'), 'Age', 0, 150)
            if action!='register_pending': severity = integer(body.get('severity'), 'Severity', 1, 4)
        if action in {'checkin', 'review_checkin', 'require_review', 'reprioritize', 'no_show', 'find_id'}:
            allowed.add('id'); ident = patient_id(body.get('id'))
        if action in {'checkin','review_checkin','reprioritize'}:
            allowed.add('severity'); severity = integer(body.get('severity'), 'Severity', 1, 4)
        if action == 'find_name':
            allowed.add('name'); name = name_value(body.get('name'))
        if action == 'report':
            allowed |= {'key', 'algorithm'}
            key = integer(body.get('key'), 'Sort key', 0, 2)
            algorithm = integer(body.get('algorithm'), 'Algorithm', 1, 2)
        if set(body) - allowed:
            raise ValueError('Unexpected fields. Patient IDs are generated by the C core, never supplied during registration.')
        pointer = self.lib.app_call(self.handle, ACTIONS[action], name.encode('utf-8'), ident,
                                    age, severity, key, algorithm)
        if not pointer:
            raise RuntimeError('C engine could not produce a response. Refresh to check current saved state.')
        try:
            return json.loads(ctypes.string_at(pointer).decode('utf-8'))
        finally:
            self.lib.app_release(pointer)


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON fields are not allowed.')
        result[key] = value
    return result


class LocalHTTPServer(HTTPServer):
    # SO_REUSEADDR on Windows can allow a second listener to share an address.
    allow_reuse_address = os.name != 'nt'

    def server_bind(self):
        if os.name=='nt':
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_EXCLUSIVEADDRUSE,1)
        super().server_bind()


class Handler(BaseHTTPRequestHandler):
    # Single-threaded HTTPServer serializes access to the C context.
    def log_message(self, *_):
        pass  # Avoid logging patient fields or session tokens.

    def send(self, status, data, content_type='application/json; charset=utf-8'):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def trusted(self):
        origin = f'http://127.0.0.1:{self.server.server_port}'
        return (self.headers.get('Host') == origin[7:]
                and self.headers.get('Origin', origin) == origin
                and self.headers.get('Sec-Fetch-Site', 'same-origin') in {'same-origin', 'none'})

    def do_GET(self):
        if not self.trusted():
            self.send(403, {'ok': False, 'message': 'Only same-origin local requests are allowed.'}); return
        if self.path == '/api/session':
            self.send(200, {'token': self.server.patient_token, 'staff_required':True, 'demo': self.server.demo}); return
        if self.path == '/api/catalog':
            self.send(200,self.server.assessments.rules.data); return
        if self.path == '/api/state':
            if not safe_token(self.headers.get('X-Clinic-Token', ''), self.server.token):
                self.send(403, {'ok': False, 'message': 'Refresh the page to reconnect.'}); return
            self.respond({'action': 'state'}); return
        assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                  '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                  '/style.css': ('style.css', 'text/css; charset=utf-8'),
                  '/patient': ('patient.html','text/html; charset=utf-8'),
                  '/patient.js': ('patient.js','text/javascript; charset=utf-8'),
                  '/patient.css': ('patient.css','text/css; charset=utf-8')}
        if self.path not in assets:
            self.send(404, {'ok': False, 'message': 'Not found.'}); return
        filename, content_type = assets[self.path]
        self.send(200, (ROOT / 'web' / filename).read_bytes(), content_type)

    def do_POST(self):
        public=self.path in {'/api/login','/api/patient/identify','/api/patient/preview','/api/patient/submit'}
        expected=self.server.patient_token if public else self.server.token
        if not self.trusted() or not safe_token(self.headers.get('X-Clinic-Token',''),expected):
            self.send(403,{'ok':False,'message':'Authorization failed. Patients use the patient page; staff must sign in.'}); return
        try:
            length=int(self.headers.get('Content-Length','0'))
            if not 0<length<=16384 or self.headers.get_content_type()!='application/json': raise ValueError('Send a JSON object of at most 16384 bytes.')
            self.connection.settimeout(5)
            body=json.loads(self.rfile.read(length).decode('utf-8'),object_pairs_hook=strict_object,
                parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Invalid JSON number.')))
            if self.server.assessments.blocked: raise RuntimeError('Storage recovery is required. Stop and restart after fixing storage.')
            if self.path=='/api/login':
                now=time.monotonic(); self.server.pin_attempts=[t for t in self.server.pin_attempts if now-t<60]
                if len(self.server.pin_attempts)>=10:
                    self.send(429,{'ok':False,'message':'Too many sign-in attempts. Wait one minute.'}); return
                if not isinstance(body,dict) or set(body)!={'pin'} or not isinstance(body['pin'],str) or not safe_token(body['pin'],self.server.staff_pin):
                    self.server.pin_attempts.append(now)
                    self.send(403,{'ok':False,'message':'Incorrect staff PIN. Use the PIN shown in the local launcher terminal.'}); return
                self.send(200,{'ok':True,'token':self.server.token}); return
            if self.path=='/api/patient/identify':
                self.send(200,{'ok':True,'identity':self.server.assessments.identify(body)}); return
            if self.path=='/api/patient/preview':
                self.send(200,{'ok':True,'evaluation':self.server.assessments.rules.evaluate(body)}); return
            if self.path=='/api/patient/submit':
                self.send(200,{'ok':True,**self.server.assessments.submit(body)}); return
            if self.path!='/api/action':
                self.send(404,{'ok':False,'message':'Not found.'}); return
            self.respond(body)
        except (ValueError,UnicodeError,TimeoutError) as error:
            self.send(400,{'ok':False,'message':str(error)})
        except Conflict as error:
            self.send(409,{'ok':False,'message':str(error)})
        except (OSError,RuntimeError) as error:
            self.send(500,{'ok':False,'message':str(error)})

    def respond(self, body):
        try:
            if not isinstance(body,dict): raise ValueError('Send an action object.')
            action=body.get('action')
            if action in ('register_pending','review_checkin','require_review','reprioritize'):
                self.send(403,{'ok':False,'message':'Use the patient submission and staff assessment review workflow.'}); return
            if action=='invite_patient':
                if set(body)!={'action','id'}: raise ValueError('Enter only the patient ID.')
                invitation=self.server.assessments.invite(body['id'])
                result=self.server.engine.call({'action':'state'}); result.update(invitation=invitation,message='Patient intake code created')
            elif action=='review_assessment':
                result=self.server.assessments.review(body)
            else:
                if action=='checkin' and self.server.assessments.has_pending(body.get('id')):
                    raise Conflict('Review the patient-submitted assessment before check-in.')
                if action=='load':
                    checkpoint=self.server.engine.lib.app_checkpoint(self.server.engine.handle)
                    if not checkpoint: raise RuntimeError('Not enough memory to reload safely.')
                    try:
                        result=self.server.engine.call(body)
                        if result['ok']: self.server.assessments.reload()
                    except Exception:
                        self.server.engine.lib.app_restore_checkpoint(self.server.engine.handle,checkpoint); checkpoint=None
                        raise
                    finally:
                        if checkpoint: self.server.engine.lib.app_discard_checkpoint(checkpoint)
                else: result=self.server.engine.call(body)
            result['assessments']=self.server.assessments.public_records()
            result['persistence']={'file':self.server.engine.path.name,'mode':'Autosave','demo':self.server.demo,
                'saved_at':self.server.engine.path.stat().st_mtime,'revision':str(self.server.engine.path.stat().st_mtime_ns)+'-'+str(self.server.assessments.path.stat().st_mtime_ns)}
            self.send(200 if result['ok'] else 409,result)
        except (ValueError,UnicodeError) as error:
            self.send(400,{'ok':False,'message':str(error)})
        except Conflict as error:
            self.send(409,{'ok':False,'message':str(error)})
        except (RuntimeError,OSError) as error:
            self.send(500,{'ok':False,'message':str(error)})


def create_server(path, port=8765, demo=False, library=None):
    engine = Engine(path, library)
    try:
        assessments=AssessmentStore(engine)
        server = LocalHTTPServer(('127.0.0.1', port), Handler)
    except Exception:
        engine.close(); raise
    server.engine, server.token, server.demo = engine, secrets.token_urlsafe(32), demo
    server.assessments=assessments; server.patient_token=secrets.token_urlsafe(32)
    server.staff_pin=''.join(secrets.choice('0123456789') for _ in range(8)); server.pin_attempts=[]
    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=ROOT / 'clinic.db')
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--demo', action='store_true', help='Use only the separate demo.db file')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    if not 0 <= args.port <= 65535:
        parser.error('--port must be between 0 and 65535')
    if args.demo and args.data != ROOT / 'clinic.db':
        parser.error('--demo cannot be combined with --data')
    path = ROOT / 'demo.db' if args.demo else args.data
    server = None
    try:
        server = create_server(path, args.port, args.demo)
        if args.demo and not server.engine.call({'action': 'state'})['state']['patients']:
            for name, age, severity in [('Alex Example', 28, 4), ('Blair Demo', 45, 1), ('Casey Sample', 33, 2), ('Drew Fictional', 22, 2)]:
                result = server.engine.call({'action': 'register_checkin', 'name': name, 'age': age, 'severity': severity})
                if not result['ok']: raise RuntimeError(result['message'])
        url = f'http://127.0.0.1:{server.server_port}'
        print(f'Smart Clinic running at {url} | {"FICTIONAL DEMO" if args.demo else "Local records"}', flush=True)
        print(f'STAFF PIN: {server.staff_pin} (local staff only; changes on restart)',flush=True)
        print(f'Patient assessment page: {url}/patient',flush=True)
        print('Stop with Ctrl+C. Every successful change is autosaved.', flush=True)
        if not args.no_browser: webbrowser.open(url)
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as error:
        print(f'Cannot start: {error}', file=sys.stderr); return 1
    finally:
        if server:
            server.server_close(); server.engine.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
