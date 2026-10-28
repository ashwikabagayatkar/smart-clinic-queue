# Smart Clinic Queue & Triage Management System

A responsive clinic application backed by real **C11 data structures**, with a separate patient-completed symptom assessment page and an authorized staff review inbox. Register patients with staff-assigned triage severity, manage a live queue and consultations, search records, inspect visit history, undo eligible check-ins, and generate reports using the C Merge Sort or Insertion Sort implementations. The original terminal interface is retained.

The web app runs locally. There is no cloud account, database server, frontend build system, CDN, or third-party runtime Python package. This is a college DSA project, not diagnostic software: staff must choose urgency; the demonstration rule engine never diagnoses or automatically assigns a final clinical priority.

## Patient self-assessment and staff review

**Patients complete the checklist themselves.** The staff workspace does not ask staff to fill in patients’ symptom answers by default. Staff review the submitted answers, warning flags and transparent demonstration suggestion, then make the actual care-priority decision.

Launch in Windows PowerShell:

```powershell
cd C:\Projects\smart-clinic-queue
.\launch.bat
# Or use separate fictional records:
.\launch.bat --demo
```

Keep the launch terminal open. It prints the local URL, an **8-digit STAFF PIN**, and the patient-page URL. PINs change on restart; do not share the PIN with patients. Open a second PowerShell window to open the patient page in a browser, or use the staff header’s **Patient page ↗** link:

```powershell
Start-Process "http://127.0.0.1:8765/patient"
```

For a different `--port`, use that port in the URL. On Linux the equivalent launch is `python3 tools/launch.py`; the same `/patient` route is used. The patient page is responsive, but a physical phone cannot reach this loopback-only server over the LAN; use a local kiosk/browser for this prototype. No public deployment was added.

### Patient steps

1. **New patient:** choose “I’m a new patient” and enter your name and age. A unique C-generated patient ID is created atomically when you submit, not when you merely open the form. You are not assigned a clinical severity or added to the queue.
2. **Existing patient:** staff find the correct patient in **Patients**, select **Patient form**, and give that patient their intake code or patient-specific link. Enter the ID and code on `/patient`. Codes are patient-bound, single-use, and expire after 24 hours; issuing a replacement invalidates an unused earlier code. A bare ID does not authorize access to another record. Verify the name/age in the review step; ask staff to resolve any mismatch before submission.
3. Select symptoms with the searchable, categorized checkboxes. Filtering does not clear selections. Explicitly confirm whether you have checked the entire list; unchecked symptoms are **not** automatically treated as absent.
4. Answer the relevant follow-ups and universal warning questions, provide duration and how severe symptoms feel to you, and add symptoms in your own words. “Unsure,” unanswered questions, and partially entered duration are retained as uncertain/incomplete; self-reported severity is not the final clinical priority.
5. Review the patient details and all answers, confirm that they belong to you, and submit. Keep the **AS-… assessment reference** and patient ID from the confirmation screen. Submission does not enter a consultation queue.

Emergency warnings show a prominent instruction to seek immediate emergency assistance and tell staff now. **Do not wait for this form, a rule result, or the consultation queue to get emergency help.** Emergency flags are retained even when the remainder of the assessment is incomplete or no rule matches.

Retries of the same immutable submission reference and answers return the same saved assessment instead of creating another patient/assessment. Conflicting reuse is rejected. The tab retains only its random submission ID, not symptom answers, in session storage. If a request times out, retry the unchanged form. Changing answers after an accepted request requires a new form/code; ask staff if you are uncertain whether a submission succeeded. Existing patients may have at most one pending assessment and cannot submit for another ID with their intake code.

### Staff steps

1. Open the staff dashboard at the root URL and sign in with the PIN printed in the launch terminal. The PIN is a **local prototype authorization gate**, not individual staff identity management. Failed sign-ins are rate-limited. Staff access tokens remain in page memory; reloading/signing out requires the PIN again. Keep staff and patient browsers/tabs separate and sign out before handing a device to a patient.
2. **Patient assessments** shows the real pending/reviewed records. A live global warning banner alerts staff to patient-reported emergency flags (polling every five seconds while the page is visible). There are no email, SMS, operating-system, or closed-browser notifications; clinics must not rely on this prototype to monitor emergencies.
3. Open an assessment. Verify the patient identity, read the actual symptom and follow-up answers (including explicit “Unanswered” values), free text, warning flags, suggested priority, rule explanation, rule IDs, source/review status and dataset version.
4. Select the **final priority 1–4 explicitly**. It is not preselected from the suggestion. Enter the reviewing staff member’s name and confirm the review checkbox. A reason is mandatory when overriding a suggestion or assigning a priority where no unique rule matched.
5. **Confirm priority & add to queue** saves the staff decision and calls the existing C review/check-in logic. Suggested priority remains separate from staff-confirmed priority and the override reason. Existing patients with pending assessments also have a persisted C review gate: ordinary check-in cannot bypass it.
6. Equal-priority patients retain the C queue’s arrival order **at staff-confirmed queue admission**, not form-opening/submission time. Review B then A at the same priority to see B called first. Levels 1–3 use the binary min-heap; level 4 uses FIFO. No review can enqueue a patient twice.
7. Undo removes an eligible check-in but retains the historical staff-review audit. If a new patient returns to “Awaiting triage” after undo, issue a fresh intake code/assessment to reassess; the old decision is not silently erased or reviewed twice.

### Transparent demonstration rules

`data/symptoms.json` contains the symptom categories, relevant follow-ups, universal warning questions, and four exact-condition rules. Each rule includes all required symptom/follow-up/warning conditions, duration bounds, self-reported severity, suggested priority, explanation, source and review status. The four scenarios demonstrate Critical, Urgent, Priority and Normal. There are **no symptom-count scores or unsupported numerical weights**.

All current rules are **demonstration-only, software-test-reviewed teaching rules — not clinically validated or clinically approved triage protocols**. Public emergency-advice URLs support the general warning messages, not validation of the exact priority rules. `demo_reviewed` means the software behavior was reviewed/tested; it does not mean a qualified clinician validated the rule. Do not deploy this dataset for real clinical decisions without a qualified clinical validation and governance process.

A suggestion appears only for one exact, software-reviewed demo rule when every relevant answer is explicit. Missing/uncertain answers, absent confirmation of other listed symptoms, unmatched or combined symptoms, extra free-text symptoms needing interpretation, unreviewed rules, and multiple matching rules return **“Staff assessment required.”** Warning flags always remain independent of a suggested priority. The rule engine runs in the backend; browser checkbox counts are only display feedback.

### Assessment persistence and recovery

The existing C snapshot remains the patient/queue/history authority. Patient answers, invitation hashes, frozen suggestion explanations and staff-review records are stored in a companion `<database>.assessments.json`. Plain intake codes are not stored. The C snapshot and assessment metadata are coordinated by `<database>.intake-journal.json`: before changing either, the server saves checksummed before-images and checkpoints the C state including undo. Successful changes save both and remove the journal. An interrupted prepared transaction is rolled back on restart **before the C file loads**; retries remain idempotent. Failed saves restore both files and C memory, not just the browser display. An unrecoverable rollback blocks further changes and preserves the journal for recovery.

With all processes stopped, **back up and restore the C database and assessment JSON together**. Preserve an existing recovery journal too; do not manually remove it or mix files from different backups. Corrupt or mismatched assessment associations fail closed instead of resetting or attaching answers to another patient. Files are not encrypted; use fictional demo data for presentations. Metadata/journal files, locks, backups and screenshots are Git-ignored. Do not edit the symptom dataset under a running server; archived suggestions retain their submitted dataset version and explanation.

## Native Windows: VS Code, MinGW-w64 GCC and mingw32-make

**Verification status: this environment is Linux, not Windows. Native Windows compilation, DLL loading, batch scripts and Windows-specific persistence have NOT been executed here.** The source/build paths are adapted for native Windows, with a Windows-only verification suite ready to run. Passing Linux tests or inspecting Windows command lines does not establish native compatibility.

Use native **Python 3.11+**, **MinGW-w64 GCC**, **mingw32-make**, and a modern Edge/Chrome/Firefox browser. Match Python and GCC architectures (64-bit is recommended). The frontend has no npm build or third-party runtime package. Normal Windows builds/tests require neither Git Bash, MSYS shell utilities, WSL, nor a Linux server.

In VS Code, open the repository folder and use its **PowerShell** terminal. Ensure your existing MinGW `bin` directory is on `Path`, then check:

```powershell
where.exe gcc
where.exe mingw32-make
gcc --version
gcc -dumpmachine
mingw32-make --version
py -3 -c "import sys, struct; print(sys.version); print(struct.calcsize('P') * 8, 'bit Python')"
```

`gcc -dumpmachine` should report a native MinGW target such as `x86_64-w64-mingw32`, not `x86_64-pc-msys` or Cygwin. If `py` is unavailable, use `python` to check your installed interpreter. The batch/Make helpers automatically try `py -3`, then `python`, and reject versions older than 3.11. The build driver rejects Python/MinGW architecture mismatches on Windows.

If needed, add your actual compiler path for the current PowerShell session (substitute your installation folder):

```powershell
$env:Path = "C:\mingw64\bin;$env:Path"
# Optional, if a different GCC is first on PATH:
$env:CC = "C:\mingw64\bin\gcc.exe"
```

An alternative is MSYS2 **UCRT64**, but it is not mandatory if your existing MinGW-w64 works. Install native UCRT packages from the UCRT64 setup terminal:

```sh
pacman -Syu
# Reopen UCRT64 and repeat if the updater requests it.
pacman -S --needed mingw-w64-ucrt-x86_64-gcc mingw-w64-ucrt-x86_64-make
```

Then add `C:\msys64\ucrt64\bin` to Windows `Path` and return to PowerShell. Do not select MSYS/Cygwin GCC for the native Python DLL. Python can be installed from <https://www.python.org/downloads/windows/> with its launcher/PATH option enabled.

### Build, test and run

Run these commands from your repository folder:

```powershell
mingw32-make all
mingw32-make test
.\run.bat
```

Equivalent batch commands, if you prefer not to invoke Make:

```powershell
.\build.bat
.\test.bat
.\run.bat
```

`build.bat`/`mingw32-make all` build the native CLI and shared C backend; the batch builder additionally prepares the C test binaries. `test` builds any missing binaries and runs the complete portable C, API, patient assessment, staff-review, rule, persistence and terminal suite. **Stop running clinic processes before rebuilding**, because Windows locks loaded DLLs/executables. Every wrapper propagates failures to its exit code; there are no interactive `pause` prompts in automated scripts.

Outputs:

```text
build/clinic.exe          Retained terminal application
build/clinic_core.dll     C library loaded by Python ctypes
build/test_clinic.exe     Core C regressions
build/test_bridge.exe     C integration/checkpoint regressions
```

VS Code tasks are supplied in `.vscode/tasks.json`: **Ctrl+Shift+B** builds; **Terminal → Run Task → Clinic: test/run** tests or launches. Do not compile `src/main.c` alone using a “run active file” extension; the application needs all core modules and Windows entry-point flags. Batch files have explicit CRLF Git attributes.

The Makefile delegates normal builds to `tools/build.py`: `-std=c11 -Wall -Wextra -Wpedantic -Werror`, explicit UTF-8 compiler charsets, MinGW ANSI stdio (`__USE_MINGW_ANSI_STDIO=1`), and static libgcc on Windows. Only the native CLI links with `-municode` and uses `wmain`; the shared library exports a C calling-convention ABI. DLL/executable suffixes are selected by the running Python OS. Build fingerprints track compiler/architecture/flags and input timestamps so an unchanged launcher does not relink a loaded DLL during tests. Core structure and sorting implementations are unchanged.

To choose a specific Python for Make, use `mingw32-make PYTHON="py -3" all` or `mingw32-make PYTHON=python all`. To clean only generated outputs, stop servers, then run `mingw32-make clean`; patient databases, assessments, locks and recovery journals outside `build/` are retained. Do not store real data under `build/`.

The default staff page opens automatically. Keep the terminal open for its staff PIN; stop with **Ctrl+C**. Open the patient page in a separate browser tab/window:

```powershell
Start-Process "http://127.0.0.1:8765/patient"
```

Other supported commands:

```powershell
.\launch.bat --demo                 # Backward-compatible alias of run.bat
.\run.bat --demo                    # Separate fictional demo.db and assessments
.\run.bat --no-browser              # Print the URLs without opening a browser
.\run.bat --port 8877               # Use another local port
.\run.bat --data "C:\Clinic Records\team.db"
.\build.bat web                     # Rebuild only the shared library if needed
.\build.bat --force                 # Force all targets to rebuild (stop servers first)
.\build\clinic.exe "C:\Clinic Records\team.db" # CLI; never concurrent with web on this file
```

The data folder must exist and be writable. The CLI converts native wide Windows arguments to UTF-8; C snapshot I/O uses wide filesystem APIs. Paths containing spaces and Unicode, intake/assessment JSON, priority queues and repeated snapshot replacement have regression tests that will also execute on Windows. Python adds the DLL directory and detected GCC `bin` directory with `os.add_dll_directory`, rather than relying on obsolete DLL search behavior.

`tests/test_portability.py` contains **three explicitly Windows-only checks**: native MinGW PE format/architecture and exported ABI; batch failure exit codes; and batch build/launch from a copied project path containing spaces. They are skipped on Linux. Run `mingw32-make test` on your actual Windows computer and retain the complete output before calling native compatibility verified. Also exercise real staff/patient browser flows and Ctrl+C in the VS Code terminal; API tests alone do not prove the Windows console/browser experience.

The server binds only `127.0.0.1`, using exclusive Windows address ownership. Staff authenticate with the ephemeral local PIN; patients cannot retrieve staff tokens from public endpoints. Do not expose/forward the port. No LAN/public deployment was added.

## Linux: build, launch and tests

Requirements: GCC with C11 support, GNU Make, Python 3.11+, a modern browser. Verified in this environment with GCC 14.2.0, Make 4.4.1, Python 3.12, and Chromium. Native Windows execution has not been available in this cloud environment; the Windows launch path and platform-specific persistence code are supplied, but must still be verified on a Windows machine.

```sh
python3 tools/launch.py               # Build the C shared library and open the UI
python3 tools/launch.py --demo         # Separate fictional demo records
make                                 # Build the terminal application and shared backend
./build/clinic                       # Terminal mode, not concurrent with web on same file
make web                             # Build the shared C library only
make test                            # Full portable C/bridge/API/assessment/terminal suite
make test-posix                      # Optional original POSIX-shell CLI harness
make sanitize                        # ASan, UBSan and leak checks: core, bridge and CLI
python3 tools/test.py                 # Same portable test workflow used on Windows
```

`make test` requires loopback sockets. In a restricted Codex sandbox, run it with the supported sandbox escalation if socket creation is blocked. Sanitizer leak checks similarly need permission to inspect processes; a ptrace restriction is not a passing test. Sanitizers are a Linux GCC development check; the Windows target explicitly reports them unsupported instead of attempting Linux environment-assignment syntax. The normal portable suite does not require a shell; only `test-posix` uses the optional historical `tests/cli.sh` harness. Compiler flags remain `-std=c11 -Wall -Wextra -Wpedantic -Werror`. Run `make clean` to remove build products; databases are preserved. Override compiler via `CC` or `make CC=clang`; clean first when changing compilers. `make PYTHON=python test` selects another Python executable.

Optional real-browser test (not required to launch the app):

```sh
python3 -m pip install playwright
python3 -m playwright install chromium
python3 tests/browser_check.py
python3 tests/patient_browser_check.py # Separate patient/staff end-to-end workflow
```

On Windows, replace `python3` with `py -3`. If using a system Chromium, set the optional `CHROMIUM` variable to its executable. The browser test uses a temporary fictional database, validates desktop/mobile behavior, and writes ignored screenshots under `build/screenshots/`.

## Workflow and severity rules

Staff registration and staff check-in require an explicit final severity. Patient self-registration is different: it creates an **Awaiting triage** record with no clinical priority, never a default severity 0. Staff review must occur before queue admission. The existing categories are:

| Value | Staff-assigned priority |
| --- | --- |
| 1 | Critical |
| 2 | Urgent |
| 3 | Priority |
| 4 | Normal |

There is **no default selection** in the UI, and missing, zero, fractional, boolean, or out-of-range severities are rejected by the backend. The staff-confirmed severity is stored in the real `Patient` record and survives save/restart. Undo restores the prior severity or explicit unassigned state, never a numeric clinical severity 0. Names may contain at most 79 UTF-8 bytes, cannot be blank or contain controls/`|`; age is an integer 0–150. Patient IDs are generated monotonically by C, never entered at registration or reused. Duplicate names are allowed; exact-name search is case-sensitive. IDs travel as decimal strings through JSON to preserve all 64 bits.

- **Overview:** real counts of waiting, critical/urgent waiting, and completed visits, plus queue preview, consultation room, recent history.
- **Patients:** register with optional immediate check-in; search by ID through the C hash table or exact name through the C BST; check in an existing non-waiting patient; open individual history.
- **Live queue:** C service order, arrival sequence, estimated waits and status. Levels 1–3 use the heap; level 4 uses FIFO. Equal priorities retain check-in order. Start one consultation, complete it, or confirm a waiting patient's no-show.
- **Undo:** the web UI finds the latest *eligible* waiting check-in by popping past stale stack entries through `clinic_undo`. Registration remains. Completed/no-show history is immutable. The retained CLI pops one entry per action and reports an ineligible entry; repeat to reach an earlier eligible one.
- **History:** filter individual/all visits and display oldest/newest first. Only completed/no-show visits enter the doubly linked list.
- **Reports:** choose name/ID/severity and Merge Sort/Insertion Sort. Sorting happens in C. Download the generated order as CSV; formula-like names are escaped for spreadsheets. Reports are invalidated after changes; counters reflect current saved history, not invented daily metrics.
- **Data & persistence:** see database filename, last save time and undo availability; explicitly save or confirm reload. Reload resets session undo history.

Waiting estimates assume 15 minutes for every patient ahead, plus one active consultation. They are workload estimates, not medical predictions. New urgent arrivals can increase waits. An active consultation is not interrupted. The browser polls every five seconds when the staff page is visible, including while review dialogs are open; refresh after a disconnected/timed-out request before retrying, as it may already have saved.

## Demo workflow (fictional records only)

Launch `launch.bat --demo` (Windows) or `python3 tools/launch.py --demo` (Linux). Only a separate `demo.db` is seeded, and only if empty; `clinic.db` is untouched. A yellow banner identifies the demo workspace. Stop the app before switching databases.

1. View the live queue: **Blair Demo (1)** precedes **Casey Sample (2)** and **Drew Fictional (2)**, who keep arrival order; **Alex Example (4)** waits last.
2. Call next, confirm, and complete Blair's consultation. Inspect Blair's individual history.
3. Undo the latest eligible check-in: Drew returns to Registered with severity 2. Search Drew by ID or exact name, then check in again with an explicitly selected severity.
4. Mark a waiting patient as no-show, confirm, and inspect the new visit entry.
5. Generate severity reports using both C sorting algorithms. Save, stop, and restart with `--demo`; statuses, visits and remaining queue order are restored. Undo resets.
6. Register another fictional patient; note the generated ID and mandatory severity. To reset demo data, stop the app and remove only `demo.db` (not your actual database). The retained `.lock` file is harmless; OS locks are released on process exit.

## Architecture and project structure

```text
Browser: web/index.html + style.css + app.js
    → same-origin JSON HTTP, session token, loopback only
Python stdlib: tools/server.py (HTTP, typed validation, locking, ctypes)
    → opaque C ABI in include/bridge.h and src/bridge.c
C11 core: clinic.c + structures.c + reports.c + persistence.c
    → validated local snapshot
```

JavaScript renders C-returned JSON; it does not implement the heap, FIFO, ID/name searches, undo stack, or report sorting. Queue snapshots are produced using C heap extraction on a pointer copy, then traversing the real FIFO. Python does not maintain its own patient registry. The server serializes requests into one C context. Before a web mutation, C clones the state including history and undo; it only accepts the operation after a successful save. A save failure restores that clone and returns an error. See [DSA_AUDIT.md](DSA_AUDIT.md) for algorithm locations, complexity and demonstrations.

```text
include/clinic.h, bridge.h       Domain APIs and opaque integration ABI
src/structures.c                Explicit heap, FIFO, linked history, chained hash, stack, BST
src/clinic.c                    Registration, queue/status transitions, estimates, undo
src/reports.c                   Stable Merge Sort and Insertion Sort
src/persistence.c               Validated snapshot read/write, Windows replacement support
src/bridge.c                    JSON serialization, C actions, autosave/rollback
src/main.c                      Retained terminal interface
web/                            Responsive dashboard, forms, dialogs and views
tools/server.py                Role-gated loopback HTTP transport and OS database lock
tools/triage.py                Exact-condition, data-driven demonstration rule engine
tools/assessment_store.py       Assessment persistence and cross-file recovery journal
data/symptoms.json              Categories, follow-ups, warning signs and demo rules
tools/build.py                 Shared strict-C11, architecture-aware build driver
tools/manage.py                Portable cleanup/process/sanitizer helpers
build.bat, run.bat, test.bat    Native Windows build/run/test wrappers
launch.bat, tools/launch.py     Backward-compatible one-command graphical launch
tools/python.bat               Native Windows Python discovery and exit-code propagation
tools/test.py                  Windows/Linux portable test runner
tools/repair_severity.py        Offline explicit staff assignment for legacy records
tests/test_clinic.c             Core DSA and severity regressions
tests/test_bridge.c             C integration, ownership and rollback regressions
tests/test_api.py               Real HTTP → C tests, locking, persistence and legacy repair
tests/test_terminal.py, cli.sh  Portable and original terminal tests
tests/test_launcher.py          One-command launch and real process restart
tests/test_triage.py            Every demo rule, missing answers, warning flags and ambiguity
tests/test_assessments.py       Authorization, identity binding, staff review and recovery
tests/patient_browser_check.py  Separate patient/staff desktop/mobile workflow
tests/browser_check.py          Optional real Chromium desktop/mobile tests
```

## Persistence, legacy records and recovery

The `CLINIC2` snapshot stores counters, patients, an explicit review gate, active consultation and completed/no-show visits. Valid older `CLINIC1` snapshots remain readable. New untriaged patient rows contain the literal `none`, not severity 0; the C API exposes `null` to the UI and uses an explicit internal `UNASSIGNED_PRIORITY` marker that cannot enter either queue. Queues and indexes are rebuilt and validated before replacing live state. Undo is session-local. Every successful web mutation is autosaved; invalid operations and save failures leave the prior state intact. CLI changes save on option 11, option 0 or EOF. A corrupt/unreadable file stops startup without silently resetting records.

Saving exclusively creates `<database>.tmp`, checks writes/close, then atomically replaces the snapshot on the tested local Linux filesystem. Windows uses UTF-8-to-wide paths, exclusive `_wopen` temporary creation (avoiding older CRTs' missing `fopen` x-mode support), and `MoveFileExW(REPLACE_EXISTING | WRITE_THROUGH)` because C `rename` does not replace an existing file there. Exact power-loss durability depends on the filesystem/OS; this is not a database transaction log or encrypted storage. Keep backups. Web processes use an OS lock (`<database>.lock`); do **not** use the terminal interface or external editors concurrently on that same file, since the legacy CLI does not participate in this lock.

Older snapshots may contain registered patients with severity 0. The fixed C loader rejects them rather than inventing urgency. With **all clinic processes stopped**, run:

```powershell
py -3 tools\repair_severity.py clinic.db
```

On Linux: `python3 tools/repair_severity.py clinic.db`. For each legacy record, a staff member must explicitly enter 1–4. The tool validates the complete candidate snapshot using the C loader, creates an untouched `clinic.db.before-triage.bak`, then replaces the file. Existing backups/candidate temp files are not overwritten. Cancelling or invalid data leaves the original intact. This tool only repairs missing registration severities; it does not guess how to repair corruption.

`.gitignore` excludes builds, Python caches, databases/temporary snapshots/backups, common secrets and private keys. Only fictional demo/test identities are supplied. Never store real patient data in source or screenshots intended for Git. Filename ignores cannot detect secrets embedded in arbitrary files or untrack already tracked files.

## Troubleshooting and limitations

| Symptom | Action |
| --- | --- |
| `py`/Python or `gcc` not found | Install the dependencies above; reopen PowerShell and check `Path`. |
| DLL load error / wrong architecture | Use 64-bit Python and UCRT64 GCC; stop all servers, remove `build/clinic_core.dll`, and relaunch. Keep GCC's `bin` on `Path`. |
| Windows denies replacing the DLL during build | Stop the running launcher/server before rebuilding; Windows locks loaded DLLs. |
| Port already in use | Stop the earlier server or launch with `--port 8877`. |
| Database already open | Stop the other web server; deleting `.lock` is not a way to release a live OS lock. |
| Legacy severity 0 | Use the explicit staff repair command above; never choose arbitrary values to make loading pass. |
| Autosave failed | Check folder permissions, space and `<database>.tmp`. Inspect a stale temp file before removing it. The failed change is rolled back. |
| Cannot load database | Preserve a copy; check format, ID uniqueness and severity. No empty reset is performed. |
| Disconnected or expired session | Restart the server if necessary and refresh the browser; its session token changes on restart. |
| Unicode/spaced paths | Native CLI uses `wmain`/UTF-8 conversion; persistence uses wide Windows file APIs. Unicode/spaced-path tests are present, but native Windows execution must still be verified. |

This app has a local shared staff-PIN gate, not individual enterprise accounts. It has no multi-clinician scheduling, network deployment support, clinical decision engine, or regulatory certification. The BST is unbalanced, the hash has fixed 127 buckets, and transaction cloning/history validation are optimized for small college-demo datasets rather than large hospital workloads. Tests do not inject malloc failures or prove crash/power-loss durability. Native Windows execution remains an explicitly unverified platform check in this Linux environment.

## Portability audit and remaining native checks

| Former platform dependency | Current handling |
| --- | --- |
| `mkdir -p`, `rm -rf` in Make | Python `Path.mkdir` / fixed-output-only `shutil.rmtree`; no POSIX utilities on normal targets. |
| Unconditional `sh tests/cli.sh`, `mktemp`, `grep`, `cmp`, POSIX traps | Full Python terminal/API harness is the default; original shell harness retained only as optional `make test-posix` on POSIX. |
| Linux executable names / `./build/...` recipes | Platform-aware `.exe` / `.dll` names and subprocess argument lists. |
| POSIX `VAR=value command` sanitizer recipes | Python environment dictionaries; sanitizer target explicitly Linux-only. |
| Hardcoded `python3` on Windows | `tools/python.bat` tries native `py -3`, then `python`; Make override remains available. |
| Divergent Make/launcher compiler commands | One fingerprinted build driver, including strict settings and MinGW flags. |
| Implicit DLL dependency search | Explicit lifetime-managed DLL directories, matching Python/compiler architectures, static libgcc. |
| Narrow Windows CLI arguments | `wmain`, `-municode`, UTF-8 input/output handling and shared wide-path probe. |
| POSIX file/VPN/process assumptions | Windows `msvcrt` locking versus POSIX `fcntl`; Windows exclusive socket binding; platform-specific launcher stop signal. No VPN/container runtime required. |

Executed in the current Linux environment: strict GCC builds, portable C/API/assessment/persistence/queue tests, Unicode/spaced paths on Linux, sanitizer checks and browser workflows. A Windows recipe dry-run is only command inspection. The initial audit had no Windows machine, MinGW cross-compiler or Wine runtime. The persistence investigation below subsequently used temporary MinGW/Wine tooling on Linux; no native Windows compile/runtime success is claimed. Run the Windows suite and GUI workflow locally; unexpected DLL locks, CRT differences, Windows Defender/file-sharing behavior, or terminal shutdown issues can only be resolved conclusively with that output.

### Windows persistence regression: SDK macro collision

A failure at the former `tests/test_clinic.c:273` was traced to the Windows SDK's
`nb30.h` defining `REGISTERED` as `0x04` after `clinic.h` had declared that enum
member as `0`. This changed the loader's status validation: registered patients
were rejected, and no-show status `4` was interpreted as registered. The public C
enum now uses `CLINIC_REGISTERED = 0`; all stored status numbers and the snapshot
format remain unchanged. Existing snapshots need no conversion. This defect was
not caused by UTF-8 paths, CRLF, permissions, file closing or temporary-file cleanup.
Save/load still return a boolean; a false result alone does not distinguish I/O
failure from rejected snapshot contents. Failed loads preserve the current clinic.

Regression coverage includes Windows headers before the clinic header, independent
registered/no-show round trips, a raw LF fixture, repeated saves, corrupt snapshots,
queue restoration and assessment review. The original failure was reproduced with
MinGW GCC 14.2 cross-compilation and Wine 10 on Linux, and the fixed C suites passed
there. **Wine is not native Windows verification**; the full native Python/DLL/batch
workflow must still be checked on your Windows machine.

Stop the clinic application, then run in PowerShell from your existing clone:

```powershell
git fetch origin
git switch --track origin/fix-windows-persistence
mingw32-make all
mingw32-make test
.\run.bat
```

If the local fix branch already exists, use `git switch fix-windows-persistence`
and `git pull --ff-only` instead of creating it again. Preserve any local edits
before switching branches; no reset or database deletion is needed. The builder
recompiles changed source/header inputs automatically.
