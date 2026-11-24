# DSA audit: graphical Smart Clinic

The web interface uses the same C11 structures as the retained terminal application. There is no mock backend, database sorting, `qsort`, or replacement JavaScript scheduler. Domain types are in `include/clinic.h`; the opaque `include/bridge.h` ABI avoids exposing C structure layouts to Python.

**Integration:** browser → same-origin local JSON HTTP → Python standard-library transport/validation → `ctypes` → `src/bridge.c` → actual C domain functions. Python holds an opaque context pointer, not another patient registry. JavaScript renders C snapshots; its display arrays are serialized results, not the authoritative DSA implementations.

Let p be registered patients, u urgent waiting patients, q normal waiting patients, v historical visits, h the BST height, and alpha = p/127. Names have a fixed 79-byte maximum, so string comparisons have bounded cost.

| Required structure | Actual source / main functions | Application integration and demonstration | Complexity |
| --- | --- | --- | --- |
| Binary min-heap | `src/structures.c`: `patient_before`, `sift_down`, `heap_push`, `heap_pop`, `heap_remove` | `clinic_checkin` inserts severity 1–3; `clinic_next` extracts the minimum. The comparator uses severity, then unique check-in sequence. Web queue serialization pops a separate pointer-array heap copy, preserving the live queue. In demo mode Blair (1) precedes Casey and Drew (2), whose tie follows arrival order. | Insert amortized O(log u), worst O(u) during growth; pop O(log u); ID removal O(u) scan plus O(log u) repair. O(u) storage. |
| FIFO queue | `src/structures.c`: `queue_push`, `queue_pop`, `queue_remove`, `queue_free` | Explicit singly linked head/tail nodes hold severity-4 patients. New arrivals append at tail; they are called from head only when the urgent heap is empty. Register two Normal patients and observe service in arrival order after urgent patients. | Enqueue/dequeue O(1); ID removal O(q). O(q) storage. |
| Doubly linked visit list | `src/structures.c`: `history_append`; `src/clinic.c`: `finish`, `clinic_complete`, `clinic_no_show`, `clinic_free` | Each completed/no-show visit has independent `prev`/`next` links. Web history serializes the list, and patient/all-history views display those records. Complete a consultation, record a no-show, then open history. Tests traverse both directions. | Append O(1); traversal/filter O(v). O(v) storage. Rendering names additionally uses hash lookup. |
| Hash table with collision handling | `src/structures.c`: `table_insert`, `table_find` | Patient ID modulo 127 selects a bucket; `Patient.hash_next` implements explicit separate chaining. ID search actions 9 and clinic transitions call `table_find`. Core tests force IDs 1, 128 and 255 into one chain and check every lookup plus an occupied-bucket miss. | Insert O(1); expected lookup O(1+alpha), worst O(p). O(p+127) storage. Buckets do not resize. |
| Undo stack | `src/structures.c`: `undo_push`, `undo_free`; `src/clinic.c`: `clinic_undo`; `src/bridge.c`: action 6 | Explicit linked LIFO records retain previous status, severity, timestamps, and visit identity. Web undo repeatedly calls the core pop operation until the latest still-waiting check-in is undone; stale entries are skipped. Register/check in a patient, undo, and confirm Registered with the same staff-assigned severity. Completed/no-show visits cannot be undone. | Stack push/pop O(1). Whole web undo of k entries also incurs k ID lookups plus one linear queue removal. O(session check-ins) storage. |
| Name BST | `src/structures.c`: `tree_insert`, `tree_search`, `tree_free` | Explicit left/right child nodes, with duplicate names inserted right. Web exact-name action 10 calls `tree_search`; it does not filter the client list to implement search. Register duplicate names and search for both; case differences do not match. Cleanup uses iterative rotations, avoiding recursive teardown of skewed trees. | Insert/search O(h), including visited matching nodes; expected O(log p) for random names, worst O(p). Cleanup O(p), O(1) auxiliary space. Unbalanced by design. |
| Merge Sort + Insertion Sort | `src/reports.c`: `compare`, `merge`, `report_merge_sort`, `report_insertion_sort` | Web Reports action 11 invokes the selected C algorithm for name/ID/stored-severity sorting, with ID tie-breaking. Both are stable for comparator-equal entries. Generate both algorithms' reports and compare order. Saving uses C Merge Sort for deterministic records; loading explicitly insertion-sorts saved check-in order to reconstruct FIFO. | Merge O(p log p), O(p) temporary space plus O(log p) recursion. Insertion best O(p), average/worst O(p²), O(1) auxiliary space. |

## Severity defect and invariants

`clinic_register` now requires an explicit fourth argument, `severity`, rejects values outside 1–4, and stores the value in the actual patient object. The CLI asks for severity; web registration has required, initially unselected radio controls. The Python boundary independently rejects missing, boolean, fractional, string and out-of-range values before calling C. C still validates severity itself. Each staff check-in requires explicit priority; patient checklist submissions instead pass their backend-generated preliminary priority through the same validated C admission logic; queue comparisons and reports use `Patient.severity`.

Undo restores the prior record's staff-assigned severity or explicit unassigned state. The C loader accepts registered records only with severity 1–4 and zero visit sequence/timestamp; it rejects legacy severity 0 instead of inventing urgency. `tools/repair_severity.py` requires staff input for every legacy record, validates the candidate using C, and retains an original backup. Patient IDs remain generated by C; supplied registration IDs/unknown API fields are rejected. Duplicate names are supported, duplicate stored IDs are rejected on load, and invalid consultation transitions fail without changing state.

## Persistence and ownership

Patient allocation is owned by the C clinic/hash table. Other structures own their nodes/storage and reference those patients. `app_open` creates one opaque context; `app_close` frees it; returned JSON is freed only with `app_release`, avoiding cross-runtime allocator mismatches on Windows.

Before each web mutation, `clone_clinic` deep-copies patients, indexes, both queues, history and the undo stack. The operation is accepted only after `clinic_save` succeeds. A failure restores the clone, including undo eligibility, status and ID counters. Save exclusively creates `.tmp` and replaces the snapshot; pre-existing temp files are left intact. Windows has explicit wide-path/file-replacement handling; Linux uses rename. This is not a claim of transaction-log or power-failure durability.

`tools/server.py` binds only `127.0.0.1`, serializes C access through a single-threaded HTTP server, enforces local Host/Origin checks, distinct patient/staff tokens, and a local staff-PIN gate, serves only allowlisted staff/patient static assets, and acquires an OS database lock. That lock coordinates web servers, not the legacy CLI or external editors; never run those on the same file concurrently. Reload validates before replacing live data and resets session undo. Every successful web change is autosaved, so process restart restores queue order, IDs, active consultation, severity and visit history.

Algorithm costs are distinct from full request costs: snapshot rendering calculates waiting estimates by scanning queues, so it can be quadratic; C cloning/rebuilding an unbalanced BST can be O(p²); snapshot loading validation can be O(p² + pv + v²). Those explicit, documented scaling limits suit a small college demonstration, not a large hospital service.

## Tests and practical demonstrations

- `tests/test_clinic.c`: all seven DSAs, heap expansion/removal invariants, empty/singleton queues, fairness ties, hash collisions, duplicate names, bounded search output, a 1,024-node skewed BST, bidirectional history, stable sorting, undo/status transitions, explicit registration severity, persistence and malformed snapshot rejection.
- `tests/test_bridge.c`: opaque context lifecycle, JSON escaping/ownership, actual C actions, failed-autosave undo rollback, and restored history/undo reset. Included in sanitizer checks.
- `tests/test_api.py`: real HTTP → C calls; severity rejection/storage/restart; priority/tie/FIFO order; both C sorts; exact ID/BST searches; generated-ID-only registration; active-consultation restart; no-shows/history; failed-save rollback for registration, queue changes, completion and undo; rejected corrupt/legacy loads; web lock and local-origin restrictions; staff-led legacy repair with backup.
- `tests/test_launcher.py`: actual one-command build/launch, HTTP registration, process stop/restart, and persisted queue/severity with session-undo reset.
- `tests/test_terminal.py` and `tests/cli.sh`: retained interactive workflow, explicit severity, input bounds, full process restart, saved states and corrupt-file protection. The Python harness also runs on Windows without a POSIX shell.
- `tests/browser_check.py`: optional real Chromium test of mandatory severity, graphical registration, priority calling, consultation completion, undo, search, patient history, reports, save, page reload, responsive overflow and JavaScript errors; separate temporary fictional data and ignored desktop/mobile screenshots.

Run `make test` and `make sanitize` on Linux, or `py -3 tools\test.py` on Windows. The optional browser test additionally requires Playwright/Chromium, documented in README. A test blocked by sandbox socket/ptrace restrictions is not counted as passing; rerun with supported permissions.

### Remaining coverage and platform limits

Allocation-failure injection is not implemented: heap expansion, queue/history/stack/BST allocation and Merge Sort temporary allocation have no forced-failure tests. Other remaining gaps include long randomized interleavings, very large collision/history/tree datasets, thousands of undo operations, full process-kill/power-loss durability, and native Windows execution in this Linux environment. Existing tests do not prove those properties. The API expects valid initialized C containers and pointers from its own callers.

## Data and Git hygiene

Demo mode seeds only a separate `demo.db` with explicitly fictional names when empty. Production-mode records and all test databases remain separate. Tests use temporary folders or ignored `build/` files. `.gitignore` excludes builds, Python caches, `.db` snapshots/locks/backups, SQLite files/sidecars, `.env` files, secrets directories and common key/credential files. Only placeholder `.env.example`/`.env.sample` files may be tracked. Filename ignores do not discover secrets embedded in source or remove already tracked files. No real patient data is supplied. Feature work is committed only on the requested branch; runtime files are excluded.

## Patient-led automatic preliminary assessment

`data/symptoms.json` is the single UTF-8 JSON catalog (64 symptoms, ten categories, 16 software-reviewed demonstration rules). `tools/triage.py` evaluates rule subsets and explicit follow-up/warning conditions; unknown is not negative. Emergency rules are evaluated first and the highest urgency among matched rules wins. Unmatched/blank/extra-text cases contribute a low-confidence Priority (3) fallback; Normal has explicit narrow conditions. Every saved evaluation retains matched/deciding IDs, selected symptoms, explanation, uncertainty flags and version. These rules are not clinically validated.

`tools/assessment_store.py` atomically self-registers/identifies the patient, evaluates answers, and uses `clinic_review_checkin` via `src/bridge.c` to assign the generated priority and admit the actual C patient immediately. The C function retains its legacy name but now serves explicit priority assignment for both automatic submissions and staff review. C checks range/state itself. The journal/checkpoint rollback coordinates snapshot and metadata; UUID retries and patient-bound single-use invitation codes prevent duplicated queue admissions or wrong-record attachments. Legacy pending records remain gated and archived explanations are not recalculated on upgrade.

Optional authorized staff overrides call `clinic_reprioritize`: urgent-to-urgent heap removal/reinsertion includes an O(n) ID scan plus O(log n) repair; crossing lanes allocates the destination before removing the source and inserts normal patients by preserved arrival order, O(n) worst case. IDs, check-in time, visit order and next-order counter stay unchanged. A heap patient moved into Normal is inserted in the actual linked FIFO by its original arrival order, maintaining service fairness. Invalid states/ranges and obsolete-visit assessments fail without mutation. The bridge checkpoint/autosave restores state on storage failure. Repeated decisions retain a review history; preliminary results remain distinct.

All seven C DSAs remain in use: binary min-heap (levels 1–3, severity then arrival), FIFO (Normal), doubly linked visits (consultation outcomes), chained hash (patient identity), linked undo stack (eligible admissions), name BST (exact searches), Merge Sort and Insertion Sort (reports). Python rule conditions and JSON metadata do not replace those structures. `src/structures.c` only changes the undo record to retain/restore `needs_review`; sorting implementations are unchanged. Undo does not erase assessment history or reenqueue a cancelled admission.

Tests cover each configured rule and explanation, all priorities, emergency precedence, concurrent symptoms, optional/unknown/negative answers, fallback, unreviewed/conflicting rules, validation, automatic C admissions, override lane transitions/fairness, undo, persistence, identity binding, duplicate/retry handling, authorization, rollback and crash journal recovery. Browser workflows verify searchable expandable categories, optional forms, receipt/backend agreement, emergency messages and staff override. Demonstration rules, shared PIN authorization, unencrypted local files, polling alerts, fixed hash buckets, unbalanced BST and lack of forced-allocation/power-loss testing remain limitations. Native Windows testing is not claimed.

## Native Windows build audit

Normal Make/batch/launcher builds now share `tools/build.py`, with native suffixes, strict C11 warnings, explicit UTF-8 charsets and MinGW ANSI stdio. Windows CLI targets use `wmain`/`-municode`; the C DLL continues using an opaque C ABI. Snapshot writes use exclusive `_wopen` temporary creation and wide replacement APIs. Python owns explicit DLL search-directory handles and uses Windows-exclusive loopback binding. Normal tests/cleanup use Python rather than POSIX shell commands; the legacy shell test remains an optional Linux target. No DSA implementation has been replaced or moved to JavaScript.

`tests/test_portability.py` checks cache stability and safe cleanup on both platforms, and declares native PE/ABI, batch exit-code and spaced-project-path tests as Windows-only. Assessment/CLI tests now include Unicode names, Unicode/spaced data paths, staff review and restart. Linux execution of these portable cases is not Windows evidence. Native Windows builds and Windows-only Python tests remain unexecuted in this environment; README records the exact `mingw32-make` and batch commands for verification.

## Windows persistence status regression

Windows `windows.h` imports NetBIOS `REGISTERED=0x04`, colliding with the original
status enum in `parse_patient`. Renaming the C member to `CLINIC_REGISTERED=0`
fixes the comparison without changing serialized statuses, queue scheduling or any
DSA implementation. `persistence_status_collision` tests registered and no-show
round trips independently, LF input, and empty restored queues; the original full
round-trip assertion is retained. Windows test compilation also includes the SDK
before `clinic.h` to guard the opposite include order. Unmodified MinGW/Wine
execution reproduced the original failure; fixed MinGW/Wine C suites pass. This is
Linux-hosted compatibility testing, not a native Windows verification claim.
