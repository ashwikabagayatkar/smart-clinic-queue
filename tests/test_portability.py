"""Portable regression checks; Windows-only execution checks are explicitly skipped elsewhere."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import build as builder
import manage

class BuildTests(unittest.TestCase):
    def test_repeat_build_keeps_library_unchanged(self):
        artifact=builder.build_target('web')
        modified=artifact.stat().st_mtime_ns
        self.assertEqual(builder.build_target('web'),artifact)
        self.assertEqual(artifact.stat().st_mtime_ns,modified)
        stamp=json.loads(Path(str(artifact)+'.build.json').read_text(encoding='utf-8'))
        for flag in ['-std=c11','-Wall','-Wextra','-Wpedantic','-Werror']:
            self.assertIn(flag,stamp['command'])

    def test_bad_compiler_fails_without_shell_fallback(self):
        with patch.dict(os.environ,{'CC':'definitely-not-a-clinic-compiler'}):
            with self.assertRaisesRegex(RuntimeError,'GCC not found'): builder.compiler_path()

    def test_clean_only_removes_build_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'build').mkdir();(root/'build'/'output').write_text('generated')
            for name in ['clinic.db','clinic.db.assessments.json','clinic.db.intake-journal.json']:
                (root/name).write_text('preserve')
            with patch.object(manage,'ROOT',root),patch.object(sys,'argv',['manage.py','clean']):
                self.assertEqual(manage.main(),0)
            self.assertFalse((root/'build').exists())
            self.assertEqual((root/'clinic.db').read_text(),'preserve')
            self.assertEqual((root/'clinic.db.assessments.json').read_text(),'preserve')
            self.assertEqual((root/'clinic.db.intake-journal.json').read_text(),'preserve')


@unittest.skipUnless(sys.platform=='win32','Requires actual native Windows; not simulated on Linux.')
class NativeWindowsTests(unittest.TestCase):
    def test_mingw_pe_artifacts_and_exported_abi(self):
        import struct
        from server import Engine
        target=builder.compiler_details(builder.compiler_path())
        self.assertIn('mingw',target)
        for name in ['web','cli']:
            artifact=builder.build_target(name)
            data=artifact.read_bytes();self.assertEqual(data[:2],b'MZ')
            offset=int.from_bytes(data[60:64],'little')
            self.assertEqual(data[offset:offset+4],b'PE\0\0')
            machine=int.from_bytes(data[offset+4:offset+6],'little')
            self.assertEqual(machine,0x8664 if struct.calcsize('P')==8 else 0x14c)
        with tempfile.TemporaryDirectory() as temp:
            engine=Engine(Path(temp)/'native.db')
            try:
                for name in ['app_open','app_close','app_call','app_release','app_checkpoint','app_restore_checkpoint','app_discard_checkpoint']:
                    self.assertTrue(getattr(engine.lib,name))
            finally: engine.close()

    def test_batch_failure_exit_code_is_preserved(self):
        result=subprocess.run(['cmd.exe','/d','/c','build.bat','invalid-target'],cwd=ROOT,capture_output=True,text=True,errors='replace',timeout=30)
        self.assertEqual(result.returncode,2,result.stdout+result.stderr)

    def test_batch_build_and_launch_help_from_space_path(self):
        import shutil
        with tempfile.TemporaryDirectory() as temp:
            copy=Path(temp)/'Clinic project with spaces';copy.mkdir()
            for name in ['tools','src','include','data']:
                shutil.copytree(ROOT/name,copy/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            for name in ['build.bat','run.bat','launch.bat']:
                shutil.copy2(ROOT/name,copy/name)
            for command in [['build.bat','cli'],['run.bat','--help'],['launch.bat','--help']]:
                result=subprocess.run(['cmd.exe','/d','/c',*command],cwd=copy,capture_output=True,text=True,errors='replace',timeout=90)
                self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertTrue((copy/'build/clinic.exe').exists());self.assertTrue((copy/'build/clinic_core.dll').exists())
