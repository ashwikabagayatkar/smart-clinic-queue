"""Windows-compatible terminal regressions, without a shell dependency."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
BINARY = Path(os.environ.get('CLINIC_BIN', ROOT / 'build' / ('clinic.exe' if os.name == 'nt' else 'clinic'))).resolve()

class TerminalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / 'fictional.db'

    def tearDown(self):
        self.temp.cleanup()

    def run_app(self, text='', expected=0):
        result = subprocess.run([str(BINARY),str(self.path)],input=text,text=True,encoding="utf-8",capture_output=True,timeout=10)
        self.assertEqual(result.returncode,expected,result.stderr)
        return result.stdout

    def test_registration_and_restart(self):
        output=self.run_app('1\nFictional Terminal\n30\n2\n2\n1\n2\n3\n4\n0\n')
        self.assertIn('severity=2 | Registered',output)
        self.assertIn('Consultation completed.',output)
        self.assertIn('severity=2 | Completed',self.run_app('7\n1\n0\n'))

    def test_unicode_patient_and_database_path_with_spaces(self):
        folder=Path(self.temp.name)/'Clinic records café Ω'
        folder.mkdir();self.path=folder/'patient records.db'
        self.assertIn('Zoë Fictional',self.run_app('1\nZoë Fictional\n30\n2\n0\n'))
        self.assertIn('Zoë Fictional',self.run_app('7\n1\n0\n'))

    def test_missing_and_invalid_severity(self):
        for severity in ['','0','5','word']:
            self.assertNotIn('ID=1',self.run_app(f'1\nInvalid Fictional\n30\n{severity}\n0\n'))

    def test_maximum_name_and_corrupt_file(self):
        self.assertIn('ID=1',self.run_app('1\n'+'X'*79+'\n30\n1\n0\n'))
        self.assertIn('Input too long',self.run_app('1\n'+'X'*80+'\n30\n1\n0\n'))
        self.path.write_text('bad data')
        self.run_app('',expected=1)
        self.assertEqual(self.path.read_text(encoding="utf-8"),'bad data')
