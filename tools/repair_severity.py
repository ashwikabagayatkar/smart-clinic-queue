"""Offline, staff-led repair of legacy severity-0 registrations. Never guesses urgency."""
import argparse
from pathlib import Path
import os
import sys

from launch import build
from server import DataLock, Engine


def repair(path, choose=input):
    path = Path(path).resolve()
    lock = DataLock(path)
    candidate = Path(str(path) + '.triage.tmp')
    backup = Path(str(path) + '.before-triage.bak')
    owned_candidate = False
    try:
        original = path.read_bytes()
        lines = original.decode('utf-8').splitlines()
        changed = 0
        for i, line in enumerate(lines):
            fields = line.split('|')
            if len(fields) == 8 and fields[0] == 'P' and fields[4] == '0':
                if fields[5] != '0':
                    raise RuntimeError('Severity 0 on a non-registered patient is corrupt; no changes made.')
                while True:
                    value = choose(f'ID {fields[1]} ({fields[2]}) — staff severity [1 Critical / 2 Urgent / 3 Priority / 4 Normal]: ')
                    if value in {'1','2','3','4'}: break
                    print('A staff-assigned value from 1–4 is required. No default is used.')
                fields[4] = value; lines[i] = '|'.join(fields); changed += 1
        if not changed:
            print('No legacy severity-0 registrations found. Nothing changed.'); return
        with candidate.open('xb') as f:
            owned_candidate = True
            f.write(('\n'.join(lines) + '\n').encode('utf-8')); f.flush(); os.fsync(f.fileno())
        validation = Engine(candidate)
        validation.close()  # The real C loader validates all indexes and history.
        with backup.open('xb') as f:
            f.write(original); f.flush(); os.fsync(f.fileno())
        os.replace(candidate, path)
        print(f'Repaired {changed} registrations. Original retained at {backup.name}.')
    finally:
        if owned_candidate and candidate.exists(): candidate.unlink()
        lock.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path)
    args = parser.parse_args()
    try:
        build(); repair(args.data); return 0
    except (OSError, RuntimeError, UnicodeError, EOFError, KeyboardInterrupt) as error:
        print(f'Repair stopped; original records were not replaced: {error}',file=sys.stderr); return 1


if __name__ == '__main__':
    raise SystemExit(main())
