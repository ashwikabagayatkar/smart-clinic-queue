#!/bin/sh
set -eu
clinic=${CLINIC_BIN:-./build/clinic}
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT HUP INT TERM
printf '1\nNormal Patient\n25\n4\n1\nUrgent Patient\n40\n1\n2\n1\n4\n2\n2\n1\n12\n3\n4\n5\n1\n9\n0\n1\n10\n0\n0\n' | "$clinic" "$tmp/clinic.db" > "$tmp/output"
grep -q 'Waiting patients in service order:' "$tmp/output"
grep -q 'ID=2 | Urgent Patient | age=40 | severity=1 | Consulting' "$tmp/output"
grep -q 'Visits=2 | completed=1 | no-shows=1' "$tmp/output"
printf '7\n2\n8\nNormal Patient\n0\n' | "$clinic" "$tmp/clinic.db" > "$tmp/reload"
grep -q 'Saved clinic loaded.' "$tmp/reload"
grep -q 'ID=2 | Urgent Patient | age=40 | severity=1 | Completed' "$tmp/reload"
grep -q 'ID=1 | Normal Patient | age=25 | severity=4 | No-show' "$tmp/reload"
printf 'invalid data\n' > "$tmp/bad.db"
cp "$tmp/bad.db" "$tmp/original"
if "$clinic" "$tmp/bad.db" < /dev/null > "$tmp/bad-output" 2>&1; then
    echo 'FAIL: corrupt file accepted' >&2; exit 1
fi
cmp "$tmp/bad.db" "$tmp/original"
printf 'garbage\n18446744073709551616\n99\n0\n' | "$clinic" "$tmp/valid.db" > "$tmp/invalid-input"
grep -q 'Number out of range.' "$tmp/invalid-input"
grep -q 'Unknown choice.' "$tmp/invalid-input"
"$clinic" "$tmp/eof.db" < /dev/null > "$tmp/eof-output"
test -s "$tmp/eof.db"
echo 'PASS: CLI workflow, persistence restart, corrupt-file protection, invalid input, EOF'

# Regression: the documented maximum name length must work in the terminal.
name79=$(awk 'BEGIN { for (i = 0; i < 79; ++i) printf "X" }')
name80="${name79}X"
printf '1\n%s\n30\n2\n0\n' "$name79" | "$clinic" "$tmp/name79.db" > "$tmp/name79-output"
grep -q "ID=1 | $name79 | age=30" "$tmp/name79-output"
printf '1\n%s\n30\n2\n0\n' "$name80" | "$clinic" "$tmp/name80.db" > "$tmp/name80-output"
grep -q 'Input too long.' "$tmp/name80-output"
if grep -q 'ID=1' "$tmp/name80-output"; then
    echo 'FAIL: oversized name registered' >&2; exit 1
fi
# Separate process restarts retain active consultation, urgent tie order, FIFO,
# history, both indexes and ID counters. Undo must reset between sessions.
printf '1\nAudit Normal One\n20\n4\n1\nAudit Normal Two\n21\n4\n1\nAudit Urgent One\n22\n1\n1\nAudit Urgent Two\n23\n1\n2\n1\n4\n2\n2\n4\n2\n3\n1\n2\n4\n1\n3\n0\n' | "$clinic" "$tmp/restart.db" > "$tmp/restart-first"
printf '7\n3\n6\n4\n10\n3\n3\n4\n3\n4\n3\n4\n1\nAudit New Patient\n24\n3\n8\nAudit New Patient\n0\n' | "$clinic" "$tmp/restart.db" > "$tmp/restart-second"
grep -q 'ID=3 | Audit Urgent One | age=22 | severity=1 | Consulting' "$tmp/restart-second"
grep -q 'No eligible operation at stack top' "$tmp/restart-second"
grep -q 'ID=5 | Audit New Patient | age=24 | severity=3 | Registered' "$tmp/restart-second"
grep -q 'ID=3 | Audit Urgent One | severity=1 | Completed' "$tmp/restart-second"
# Exactly the expected service order after finishing the restored consultation.
awk '/\| Consulting/ { if ($0 ~ /ID=4 /) print 4; else if ($0 ~ /ID=1 /) print 1; else if ($0 ~ /ID=2 /) print 2; }' "$tmp/restart-second" > "$tmp/called"
printf '4\n1\n2\n' > "$tmp/expected-called"
cmp "$tmp/called" "$tmp/expected-called"
echo 'PASS: name-length boundaries and full state across process restarts'

for severity in 0 5 missing; do
    if [ "$severity" = missing ]; then severity=''; fi
    printf '1\nInvalid Triage\n25\n%s\n0\n' "$severity" | "$clinic" "$tmp/invalid-severity.db" > "$tmp/invalid-severity-output"
    if grep -q 'ID=1' "$tmp/invalid-severity-output"; then
        echo 'FAIL: invalid or missing registration severity accepted' >&2; exit 1
    fi
done
echo 'PASS: registration rejects missing/invalid severity'
