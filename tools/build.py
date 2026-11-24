"""Portable strict-C11 build driver for native MinGW-w64/Windows and Linux GCC."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parent.parent
CORE = ['src/structures.c','src/clinic.c','src/reports.c','src/persistence.c']
STRICT = ['-std=c11','-Wall','-Wextra','-Wpedantic','-Werror','-O2',
          '-finput-charset=UTF-8','-fexec-charset=UTF-8','-Iinclude']


def compiler_path():
    requested = os.environ.get('CC','gcc')
    compiler = shutil.which(requested)
    if not compiler:
        raise RuntimeError('GCC not found. Put native MinGW-w64 GCC bin on PATH or set CC to the full gcc.exe path (not compiler flags).')
    return compiler


def windows_flags():
    return ['-D__USE_MINGW_ANSI_STDIO=1','-D_WIN32_WINNT=0x0A00','-DWINVER=0x0A00','-static-libgcc'] if os.name == 'nt' else []


def compiler_details(compiler):
    target = subprocess.check_output([compiler,'-dumpmachine'],text=True).strip()
    if os.name == 'nt':
        if 'mingw' not in target:
            raise RuntimeError(f'Use native MinGW-w64 GCC, not an MSYS/Cygwin compiler. Compiler target: {target}')
        bits = 64 if target.startswith('x86_64') else 32 if target.startswith(('i686','i386')) else None
        if bits != struct.calcsize('P') * 8:
            raise RuntimeError(f'Python/MinGW architecture mismatch: Python is {struct.calcsize("P")*8}-bit; GCC target is {target}. Install matching tools.')
    return target


def build_target(name, force=False):
    compiler = compiler_path(); target_machine = compiler_details(compiler)
    folder = ROOT/'build'; folder.mkdir(exist_ok=True)
    ext = '.exe' if os.name == 'nt' else ''
    targets = {
        'cli': ('clinic'+ext, [*CORE,'src/main.c'], ['-municode'] if os.name=='nt' else []),
        'web': ('clinic_core.dll' if os.name=='nt' else 'clinic_core.so', [*CORE,'src/bridge.c'], ['-shared',* ([] if os.name=='nt' else ['-fPIC'])]),
        'test-core': ('test_clinic'+ext, ['tests/test_clinic.c',*CORE], []),
        'test-bridge': ('test_bridge'+ext, ['tests/test_bridge.c','src/bridge.c',*CORE], [])
    }
    filename, sources, extra = targets[name]
    output = folder/filename
    command = [compiler,*STRICT,*windows_flags(),*sources,*extra,'-o',str(output)]
    stamp = folder/(filename+'.build.json')
    fingerprint = {'command':command,'platform':sys.platform,'machine':target_machine,
                   'compiler_mtime':Path(compiler).stat().st_mtime_ns}
    inputs = [ROOT/p for p in sources]+list((ROOT/'include').glob('*.h'))+[Path(__file__)]
    current = False
    if stamp.exists():
        try: current = json.loads(stamp.read_text(encoding='utf-8'))==fingerprint
        except (ValueError,OSError): pass
    if force or not output.exists() or not current or any(p.stat().st_mtime_ns>output.stat().st_mtime_ns for p in inputs):
        try:
            subprocess.run(command,cwd=ROOT,check=True)
        except subprocess.CalledProcessError:
            raise RuntimeError('C build failed. On Windows, stop every running clinic server before replacing its loaded DLL/executable. Compiler diagnostics appear above.') from None
        stamp.write_text(json.dumps(fingerprint,indent=2),encoding='utf-8')
    return output


def build(target='all', force=False):
    if target == 'all':
        return [build_target(name,force) for name in ('cli','web','test-core','test-bridge')]
    return build_target(target,force)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target',choices=['all','cli','web','test-core','test-bridge'],default='all',nargs='?')
    parser.add_argument('--force',action='store_true')
    args=parser.parse_args()
    try:
        outputs=build(args.target,args.force)
        for output in outputs if isinstance(outputs,list) else [outputs]: print(f'Built: {output.relative_to(ROOT)}')
        return 0
    except (OSError,RuntimeError,subprocess.CalledProcessError) as error:
        print(f'Build failed: {error}',file=sys.stderr); return 1


if __name__=='__main__': raise SystemExit(main())
