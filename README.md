# Smart Clinic Queue & Triage Management System

A menu-driven terminal application written in pure C11, with explicitly implemented data structures. No third-party libraries or database server are required. This is an educational scheduling system; severity is entered by the operator, not inferred as a medical diagnosis.

## Build and run

Requirements: a C11 compiler and GNU Make. Verified with GCC 14.2.0 and GNU Make 4.4.1 on Linux.

```sh
make
./build/clinic
# Or use a separate data file (quote paths containing spaces):
./build/clinic /path/to/clinic.db
```

The default data file is `clinic.db` in the current working directory. The parent directory must exist and be writable. Data loads on startup and saves using menu option 11, option 0, or end-of-input. Changes are held in memory until a successful save; save regularly. An interrupted process may lose changes made since the last save.

```sh
make test       # Core assertions and scripted terminal/restart tests
make sanitize   # Same workflows with address, undefined-behavior and leak checks
make clean      # Remove build outputs; preserve clinic data
```

Sanitizer checks require GCC/Clang sanitizer support and an environment that permits leak detection to inspect processes. In a restricted Codex command sandbox, run `make sanitize` with the approved sandbox escalation if LeakSanitizer reports a ptrace restriction. The application and C tests use C11; the terminal test harness additionally uses a POSIX shell, `mktemp`, `grep`, `cmp`, and standard file utilities. Override the compiler with `make CC=clang`. Rebuild with `make clean` after changing compiler flags.

## Typical workflow

1. Register a patient with a nonempty name and age from 0 through 150. Registration assigns a unique, monotonically increasing 64-bit ID; duplicate names are allowed. Names support at most 79 bytes and cannot contain control characters or `|`.
2. Check in by ID with severity **1 critical**, **2 urgent**, **3 priority**, or **4 normal**. A registered, completed, or no-show patient can check in; waiting or consulting patients cannot check in twice.
3. View the queue with option 12. Start the next consultation with option 3. Levels 1–3 are served before level 4; lower severity numbers come first, with check-in order breaking ties. Normal patients are served FIFO. There is one clinician and one active consultation; an arriving urgent patient does not interrupt an active consultation.
4. Complete the active consultation with option 4, or mark a waiting patient as a no-show with option 5. Both operations append an immutable visit-history entry. No-show patients leave the queue immediately. No-shows are explicitly marked by an operator; no automatic timeout is assumed.
5. Option 6 pops the latest session check-in from the undo stack. It succeeds only if that same visit is still waiting, restoring the previous status, severity, check-in time, and visit identity. An ineligible top entry is discarded with a message; another undo can then inspect the next entry. Registration itself is retained, IDs are never reused, and consultations/history are never undone.
6. Search by ID (7), search all exact, case-sensitive name matches (8), view reports (9), or browse visit history for one patient or all patients (10).
7. Save (11), or save and exit (0). A failed save is reported; exit returns a nonzero status if saving fails.

Waiting estimates assume **15 minutes per consultation**: the number of patients ahead, plus one if a consultation is active, multiplied by 15. They are workload estimates rather than elapsed-time predictions. Future urgent arrivals can increase a normal patient's wait, and sustained urgent traffic can starve the normal queue.

Reports list all patients sorted by name, ID, or severity, using the selected Merge Sort or Insertion Sort implementation. Ties use patient ID. Severity 0 means never checked in and sorts before 1–4; completed/no-show patients retain the severity of their latest visit. Reports include queue, consultation, completed-visit, and no-show counts. History stores check-in and end times as Unix timestamps on the tested platform; it can be traversed forward and backward through the doubly linked list.

## Modules and data structures

```text
include/clinic.h       Shared domain types and module APIs
src/structures.c       Binary min-heap, FIFO, chained hash table, name BST,
                       doubly linked visit list, linked undo stack
src/clinic.c           Registration, state transitions, scheduling, estimates
src/reports.c          Stable Merge Sort and Insertion Sort
src/persistence.c      Versioned text snapshots, validation, index rebuilding
src/main.c             Input validation and terminal menus
tests/test_clinic.c    Core/data-structure/persistence tests
tests/cli.sh           End-to-end terminal and restart tests
Makefile               Strict C11 build, test and sanitizer targets
```

| Structure | Purpose | Typical operation cost |
| --- | --- | --- |
| Binary min-heap | Severity 1–3, keyed by severity then check-in sequence | Insert/pop O(log n); removal by ID O(n) |
| Linked FIFO queue | Severity 4 | Enqueue/dequeue O(1); removal by ID O(n) |
| Doubly linked list | Completed and no-show visits | Append O(1); history traversal O(v) |
| Hash table with separate chaining | Patient-ID lookup, including collisions | Expected O(1 + load factor), worst O(p) |
| Linked stack | Session check-in undo records | Push/pop O(1), plus queue removal |
| Unbalanced binary search tree | Exact patient-name searches with duplicates | O(h + matches), worst O(p) |
| Merge Sort | Patient reports | O(p log p) time, O(p) auxiliary space |
| Insertion Sort | Patient reports | O(p²) time, O(1) auxiliary space |

Patient objects have one owner (the clinic's hash table). Other structures reference those objects; each owns its own nodes/storage. A snapshot of report pointers can be sorted without changing queue order. All patient/name/history/undo nodes and heap storage are freed at shutdown. The hash table has 127 buckets; it handles collisions by chaining rather than resizing. The name BST is intentionally unbalanced. Queue display and waiting estimates scan the current patients/queues; these choices suit a small educational clinic.

## Persistence and recovery

The versioned `CLINIC1` text format stores next-ID/check-in counters, patients, their latest state, active consultation, and completed/no-show history, followed by an `END` marker. Queue order is rebuilt from saved check-in sequence values; hash and name indexes are rebuilt from patient records. Undo is deliberately session-local and resets on restart.

Saving writes an exclusively created `<data-file>.tmp`, checks writes/close, and renames it over the destination. On the tested Linux filesystem, successful rename atomically replaces the snapshot. This is not a power-loss durability guarantee (`fsync` is outside C11), and concurrent application instances using the same data file are unsupported. An existing `.tmp` file causes a safe save failure; inspect it before manually removing it. Back up your data file before editing it.

Loading validates format/version, numeric ranges, IDs, sequence uniqueness, statuses, history references, and state/history consistency before replacing the live clinic. Malformed or unreadable data stops startup without overwriting the file. A failed library-level load preserves the previous in-memory state. Missing files start an empty clinic. This format is not encrypted and is intended for development/demo data.

## Validation coverage

Core tests cover empty structures; heap expansion, arbitrary removal and ordering invariants; FIFO edge removals; hash collisions; duplicate-name and missing-name search; invalid registration; priority/tie/FIFO service order; consultation transitions; waiting estimates; no-shows; undo/re-check-in behavior; bidirectional history; both sorting algorithms; empty/populated saves; restored active consultations; queue reconstruction; repeated saves; and rejection of malformed/inconsistent snapshots without damaging live state.

The terminal tests register and triage patients, display the queue, complete a visit, record a no-show, inspect reports/history, restart from the saved file, search patients, reject corrupt startup files without overwriting them, handle malformed input, and exit safely on EOF.

## DSA audit

See [DSA_AUDIT.md](DSA_AUDIT.md) for implementation locations, application integration, precise complexity qualifications, remaining test gaps, and the final audit fixes. Regression coverage also includes singleton queues/history, bounded BST output, a 1,024-node skewed name tree, explicit collision-chain lookup, stable sorting, maximum-length terminal names, and active-consultation/priority/FIFO restoration across separate processes.

Database patterns (`*.db`, `*.sqlite`, `*.sqlite3`, and their dot-suffixed temporary/backup files) are ignored at every directory depth. Common local secret paths (`.env*`, `secrets/`, private keys, and credential JSON files) are ignored; `.env.example` and `.env.sample` remain trackable and must contain placeholders only. Gitignore is a filename filter, not a secret scanner: arbitrary filenames, already tracked files, and secrets embedded in source still require review. Only fictional test/demo records are supplied.
