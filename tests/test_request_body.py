"""Deterministic POST body/authorization ordering checks, without socket timing."""
from email.message import Message
import io
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from server import Handler


class RequestBodyTests(unittest.TestCase):
    def handler(self, body, *, authorized=False, length=None):
        handler = Handler.__new__(Handler)
        handler.path = '/api/action'
        handler.headers = Message()
        handler.headers['Content-Type'] = 'application/json'
        handler.headers['Content-Length'] = str(len(body) if length is None else length)
        handler.headers['X-Clinic-Token'] = 'staff' if authorized else 'patient'
        handler.server = SimpleNamespace(token='staff', patient_token='patient',
                                         assessments=SimpleNamespace(blocked=False))
        handler.trusted = Mock(return_value=True)
        handler.connection = Mock()
        handler.rfile = io.BytesIO(body)
        handler.send = Mock()
        handler.respond = Mock()
        return handler

    def test_unauthorized_body_consumed_exactly_before_403_without_parsing(self):
        for body in (b'{"action":"register","name":"Fictional"}', b'not JSON', b'\xff', b' ' * 16384):
            with self.subTest(size=len(body)):
                handler = self.handler(body, length=len(body))
                handler.rfile = io.BytesIO(body + b'UNREAD')

                def sent(status, payload):
                    self.assertEqual(status, 403)
                    self.assertFalse(payload['ok'])
                    self.assertEqual(handler.rfile.tell(), len(body))

                handler.send.side_effect = sent
                with patch('server.json.loads', side_effect=AssertionError('Unauthorized JSON parsed')):
                    handler.do_POST()
                handler.send.assert_called_once()
                handler.connection.settimeout.assert_called_once_with(5)
                handler.respond.assert_not_called()
                self.assertEqual(handler.rfile.read(), b'UNREAD')

    def test_untrusted_origin_body_consumed_without_dispatch(self):
        handler = self.handler(b'{}', authorized=True)
        handler.trusted.return_value = False
        handler.do_POST()
        self.assertEqual(handler.rfile.tell(), 2)
        self.assertEqual(handler.send.call_args.args[0], 403)
        handler.respond.assert_not_called()

    def test_invalid_length_or_content_type_is_rejected_without_reading(self):
        for authorized in (False, True):
            for length in ('0', '-1', '16385', 'invalid'):
                with self.subTest(authorized=authorized, length=length):
                    handler = self.handler(b'{}', authorized=authorized, length=length)
                    handler.rfile = Mock()
                    handler.do_POST()
                    self.assertEqual(handler.send.call_args.args[0], 400 if authorized else 403)
                    handler.rfile.read.assert_not_called()
                    handler.respond.assert_not_called()
            handler = self.handler(b'{}', authorized=authorized)
            handler.headers.replace_header('Content-Type', 'text/plain')
            handler.do_POST()
            self.assertEqual(handler.send.call_args.args[0], 400 if authorized else 403)
            self.assertEqual(handler.rfile.tell(), 0)

    def test_incomplete_body_is_rejected_without_dispatch(self):
        for authorized in (False, True):
            with self.subTest(authorized=authorized):
                handler = self.handler(b'{}', authorized=authorized, length=3)
                handler.do_POST()
                self.assertEqual(handler.send.call_args.args[0], 400 if authorized else 403)
                self.assertTrue(handler.close_connection)
                handler.respond.assert_not_called()

    def test_read_timeout_is_rejected_without_dispatch(self):
        for authorized in (False, True):
            with self.subTest(authorized=authorized):
                handler = self.handler(b'{}', authorized=authorized)
                handler.rfile = Mock()
                handler.rfile.read.side_effect = TimeoutError('timed out')
                handler.do_POST()
                handler.connection.settimeout.assert_called_once_with(5)
                handler.rfile.read.assert_called_once_with(2)
                self.assertEqual(handler.send.call_args.args[0], 400 if authorized else 403)
                self.assertTrue(handler.close_connection)
                handler.respond.assert_not_called()

    def test_authorized_json_still_validated_before_dispatch(self):
        for body in (b'{', b'{"action":"state","action":"register"}', b'{"age":NaN}', b'\xff'):
            with self.subTest(body=body):
                handler = self.handler(body, authorized=True)
                handler.do_POST()
                self.assertEqual(handler.send.call_args.args[0], 400)
                handler.respond.assert_not_called()
        handler = self.handler(b'{"action":"state"}', authorized=True)
        handler.do_POST()
        handler.respond.assert_called_once_with({'action': 'state'})
        handler.send.assert_not_called()
