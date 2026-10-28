"""Portable full C, bridge, API, assessment and terminal test runner; no shell needed."""
import subprocess
import sys
from build import ROOT, build


def main():
    try:
        build('all')
        for target in ('test-core','test-bridge'):
            subprocess.run([str(build(target))],cwd=ROOT,check=True)
        subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_*.py','-v'],cwd=ROOT,check=True)
        print('PASS: complete portable core, bridge, terminal, patient/staff API, triage and persistence suite')
        return 0
    except (OSError,RuntimeError,subprocess.CalledProcessError) as error:
        print(f'Tests failed: {error}',file=sys.stderr);return 1


if __name__=='__main__':raise SystemExit(main())
