"""Shell-independent filesystem, process and sanitizer helpers for GNU Make."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
ROOT=Path(__file__).resolve().parent.parent


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['mkdir','clean','run','sanitize','posix-test'])
    parser.add_argument('arguments',nargs='*')
    args=parser.parse_args()
    try:
        if args.action=='mkdir':
            for path in args.arguments: (ROOT/path).mkdir(parents=True,exist_ok=True)
        elif args.action=='clean':
            # Only this known output directory is removable; runtime records stay intact.
            shutil.rmtree(ROOT/'build',ignore_errors=False) if (ROOT/'build').exists() else None
        elif args.action=='run':
            if not args.arguments: parser.error('run needs an executable')
            subprocess.run([str((ROOT/args.arguments[0]).resolve()),*args.arguments[1:]],cwd=ROOT,check=True)
        elif args.action=='posix-test':
            if os.name=='nt': raise RuntimeError('The optional historical shell harness is POSIX-only. Use mingw32-make test for the portable full suite.')
            subprocess.run(['sh','tests/cli.sh'],cwd=ROOT,check=True)
        else:
            if os.name=='nt': raise RuntimeError('This sanitizer target is supported on Linux GCC only; use mingw32-make test on Windows.')
            environment=dict(os.environ,ASAN_OPTIONS='detect_leaks=1')
            subprocess.run([str(ROOT/'build/test_sanitize')],cwd=ROOT,env=environment,check=True)
            subprocess.run([str(ROOT/'build/test_bridge_sanitize')],cwd=ROOT,env=environment,check=True)
            environment['CLINIC_BIN']=str(ROOT/'build/clinic_sanitize')
            subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_terminal.py','-v'],cwd=ROOT,env=environment,check=True)
        return 0
    except (OSError,RuntimeError,subprocess.CalledProcessError) as error:
        print(f'Command failed: {error}',file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
