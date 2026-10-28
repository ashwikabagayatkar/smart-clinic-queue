# Final DSA audit

All seven requirements are genuine C implementations, called by the application. No library containers or `qsort` substitute for the required structures or sorting algorithms. Types and public APIs live in `include/clinic.h`.

Here, p = registered patients, u = urgent patients waiting, q = normal patients waiting, v = historical visits, h = name-tree height, and alpha = p / 127. Name comparisons examine at most 79 bytes.

| Requirement | Source and main functions | Application use | Complexity |
| --- | --- | --- | --- |
| Binary min-heap | `src/structures.c`: `patient_before`, `heap_push`, `sift_down`, `heap_pop`, `heap_remove` | `clinic_checkin` inserts severities 1–3; `clinic_next` extracts the minimum; undo/no-show removes a waiting entry. Array children are 2i+1 and 2i+2; parents are (i-1)/2. Priority is severity then check-in sequence. | Push amortized O(log u), worst O(u) when resizing; pop O(log u); remove by ID O(u) search plus O(log u) repair. O(u) storage. |
| FIFO queue | `src/structures.c`: `queue_push`, `queue_pop`, `queue_remove` | Severity 4 check-ins append at tail; consultation removes from head when urgent heap is empty. Explicit head/tail linked nodes. | Enqueue/dequeue O(1); remove by ID O(q). O(q) storage. |
| Doubly linked history | `src/structures.c`: `history_append`; `src/clinic.c`: `finish`, `clinic_complete`, `clinic_no_show`, `clinic_free` | Completed/no-show visits append immutable records with both prev/next links. `src/main.c:history` displays visits; persistence iterates them. | Append O(1); forward/backward traversal O(v); patient filtering O(v). O(v) storage. No random access index. |
| Hash table | `src/structures.c`: `table_insert`, `table_find` | `clinic_register` indexes unique IDs; check-in, undo, no-show and ID search resolve patients. ID modulo 127 selects a bucket; `Patient.hash_next` explicitly chains collisions. | Insert O(1); expected lookup O(1+alpha), worst O(p). O(p+127) storage. Fixed buckets, no automatic resizing. |
| Undo stack | `src/structures.c`: `undo_push`, `undo_free`; `src/clinic.c`: `clinic_undo` | Successful check-ins push linked records containing previous state and new visit identity. Undo pops only the top entry, restores it if still waiting, and consumes ineligible entries without changing consultation/history. Session-local. | Stack push/pop O(1); whole undo additionally incurs ID lookup and heap/FIFO removal, worst O(p+u+q). O(check-ins in session) storage. |
| Name BST | `src/structures.c`: `tree_insert`, `tree_search`, `tree_free` | Registration inserts into explicit left/right child nodes; menu 8 searches exact case-sensitive names, including duplicates. Equal names insert to the right; search follows that path, descending left again when a larger intervening name is encountered. Cleanup uses iterative rotations. | Insert/search O(h), including visited matches on that search path; random insertion usually O(log p), worst O(p). Free O(p), O(1) auxiliary space. Tree storage O(p). No balancing or deletion. |
| Merge Sort and Insertion Sort | `src/reports.c`: `compare`, `merge`, `report_merge_sort`, `report_insertion_sort` | Menu 9 selects either real algorithm for reports sorted by name, ID or severity, with ID tie-breaking. Persistence uses Merge Sort for deterministic patient order and explicit Insertion Sort to rebuild FIFO order. | Merge Sort O(p log p), O(p) temporary storage plus O(log p) recursion. Insertion Sort best O(p), average/worst O(p²), O(1) auxiliary space. Both stable for comparator-equal entries. |

These costs describe the structures/algorithms, not every caller. Registration also inserts into the name tree. The terminal name search allocates a patient-pointer snapshot in O(p), even though the BST search itself is O(h). Reports/queue display print waiting estimates that scan queues, so total output work can be quadratic. Snapshot validation scans history for every patient and checks visit uniqueness linearly: loading is O(p² + pv + v²) in the worst case. These are scaling limitations, not simulated structures.

## Coverage and remaining gaps

Added audit tests cover singleton FIFO removal/reuse, singleton history links, singleton heap extraction, explicit collision chains and misses in occupied buckets, bounded BST output with a sentinel, a 1,024-node all-equal skewed tree, stale/consulting undo entries, stable comparator-equal sorting, and sorted/reverse-sorted inputs. Existing tests cover heap growth and arbitrary removal invariants, FIFO edge removals, severity ties, consultations, no-shows, backward history traversal, undo of completed/no-show re-check-ins, and malformed snapshots.

The following tests remain absent; they are not claimed as passing:

| Area | Remaining edge-case tests |
| --- | --- |
| Heap | Allocation-failure injection on expansion; long randomized interleavings of push/pop/remove. |
| FIFO | Allocation-failure injection; long randomized enqueue/remove/dequeue sequences. |
| History | Allocation failure before finishing a visit; very large historical workloads. |
| Hash | Extremely high load factors and large collision chains rebuilt across persistence. Collision handling itself has explicit tests. |
| Undo | Allocation failure during stack push/queue insertion rollback; thousands of consecutive LIFO undos. |
| BST | Allocation-failure rollback; much larger adversarial trees and mixed duplicate-name distributions. Bounded results and a degenerate tree are tested. |
| Sorts | Merge temporary-allocation failure and very large arrays near practical memory limits. Stability, ties, empty/singleton, sorted/reverse and mixed inputs are tested. |

The API assumes non-null initialized containers and valid pointers supplied by its own callers. Fault injection for malloc/realloc is not implemented. Sanitizers exercise successful allocations but do not prove out-of-memory recovery.

## Persistence and data audit

`tests/cli.sh` runs separate application processes against temporary fictional databases. It verifies saved IDs, exact-name lookup, completed/no-show states, history, an active consultation, urgent tie order, normal FIFO order, the next registration ID, and session-local undo reset after restart. Core tests also verify failed loads leave the live clinic intact. Audit tests do not write to the existing interactive demo database.

The existing local `clinic.db` contains only the three fictional demo identities created in this session: Alex Example, Blair Demo, and Casey Sample. Source/test fixtures are also fictional. No database or secret file is tracked. This inspection found no real patient data in the project; it does not establish anything about external files or future user input.

Previously `.gitignore` covered only the root default database and did not cover secrets. It now excludes custom/nested `.db`, `.sqlite`, `.sqlite3` files and dot-suffixed temporary/backups and SQLite sidecars, `.env`/`.env.*` (except example/sample templates), `secrets/`, credential JSON names and PEM/key files. Ignore checks use filenames only and do not read credential contents. Filename exclusions cannot detect secrets embedded in source or in arbitrary filenames, and do not untrack already tracked files.

## Confirmed defects fixed

1. `src/main.c:read_line` rejected a valid 79-byte name because a full input buffer was mistaken for overflow before consuming its newline. It now checks the next character: a newline/EOF accepts the maximum length; extra content rejects and drains the line. Regression tests verify 79-byte acceptance and 80-byte rejection.
2. `.gitignore` lacked custom database and common secret-file exclusions. Patterns now cover nested local data and secrets, with placeholder templates explicitly allowed.

No defect was found in the seven DSA implementations during this audit. All work remains uncommitted. The full initial project is still untracked relative to the repository's initial commit; the separate audit patch isolates changes made during this audit from the pre-audit implementation.
