#include "clinic.h"
#include <errno.h>
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

static bool read_line(const char *prompt, char *buf, size_t capacity) {
    fputs(prompt, stdout); fflush(stdout);
    if (!fgets(buf, (int)capacity, stdin)) return false;
    char *nl = strchr(buf, '\n');
    if (nl) *nl = '\0';
    else {
        /* A full buffer can still be a valid maximum-length line. */
        int ch = getchar();
        if (ch != '\n' && ch != EOF) {
            while ((ch = getchar()) != '\n' && ch != EOF) {}
            buf[0] = '\0'; puts("Input too long.");
        }
    }
    return true;
}
static bool read_number(const char *prompt, uint64_t *value) {
    char buf[80];
    if (!read_line(prompt, buf, sizeof buf)) return false;
    if (!*buf) { puts("Enter a nonnegative integer."); return false; }
    for (char *p = buf; *p; ++p)
        if (*p < '0' || *p > '9') { puts("Enter a nonnegative integer."); return false; }
    errno = 0; char *end;
    uintmax_t n = strtoumax(buf, &end, 10);
    if (errno || *end || n > UINT64_MAX) { puts("Number out of range."); return false; }
    *value = (uint64_t)n; return true;
}
static void print_patient(const Clinic *c, const Patient *p) {
    printf("ID=%" PRIu64 " | %s | age=%u | severity=%u | %s", p->id, p->name, p->age, p->severity, status_name(p->status));
    size_t wait = clinic_wait_minutes(c, p->id);
    if (wait != SIZE_MAX) printf(" | estimated wait=%zu min", wait);
    putchar('\n');
}
static void report(Clinic *c) {
    uint64_t key, algorithm;
    if (!read_number("Sort by: 0=name, 1=ID, 2=severity: ", &key) || key > 2 ||
        !read_number("Algorithm: 1=Merge Sort, 2=Insertion Sort: ", &algorithm) || algorithm < 1 || algorithm > 2) {
        puts("Invalid report selection."); return;
    }
    size_t n; Patient **a = clinic_patients(c, &n);
    if (!a) { puts("Out of memory."); return; }
    bool ok = true;
    if (algorithm == 1) ok = report_merge_sort(a, n, (ReportKey)key);
    else report_insertion_sort(a, n, (ReportKey)key);
    if (!ok) puts("Out of memory.");
    else {
        for (size_t i = 0; i < n; ++i) print_patient(c, a[i]);
        size_t visits = 0, completed = 0, missed = 0;
        for (Visit *v = c->history_head; v; v = v->next) {
            ++visits; if (v->outcome == COMPLETED) ++completed; else ++missed;
        }
        printf("Patients=%zu | urgent waiting=%zu | normal waiting=%zu | consulting=%u\n"
               "Visits=%zu | completed=%zu | no-shows=%zu\n", n, c->urgent.size, c->normal.size,
               c->active ? 1u : 0u, visits, completed, missed);
    }
    free(a);
}
static void show_queue(const Clinic *c) {
    if (c->active) { puts("Current consultation:"); print_patient(c, c->active); }
    size_t count; Patient **a = clinic_patients(c, &count);
    if (!a) { puts("Out of memory."); return; }
    size_t n = 0;
    for (size_t i = 0; i < count; ++i) if (a[i]->status == WAITING) a[n++] = a[i];
    /* Sort the report snapshot, leaving the actual heap and FIFO untouched. */
    for (size_t i = 1; i < n; ++i) {
        Patient *p = a[i]; size_t j = i;
        while (j && patient_before(p, a[j - 1])) { a[j] = a[j - 1]; --j; }
        a[j] = p;
    }
    puts("Waiting patients in service order:");
    for (size_t i = 0; i < n; ++i) print_patient(c, a[i]);
    if (!n) puts("Queue empty.");
    free(a);
}
static void history(const Clinic *c) {
    uint64_t id;
    if (!read_number("Patient ID (0=all): ", &id)) return;
    if (id && !table_find(c, id)) { puts("Patient not found."); return; }
    size_t count = 0;
    for (Visit *v = c->history_head; v; v = v->next) {
        if (id && v->patient_id != id) continue;
        Patient *p = table_find(c, v->patient_id);
        printf("Visit=%" PRIu64 " | ID=%" PRIu64 " | %s | severity=%u | %s | check-in=%jd | end=%jd\n",
            v->order, v->patient_id, p->name, v->severity, status_name(v->outcome),
            (intmax_t)v->checked_in, (intmax_t)v->ended); ++count;
    }
    if (!count) puts("No completed or missed visits.");
}
int main(int argc, char **argv) {
    if (argc > 2) { fprintf(stderr, "Usage: %s [data-file]\n", argv[0]); return EXIT_FAILURE; }
    const char *path = argc == 2 ? argv[1] : "clinic.db";
    Clinic c; clinic_init(&c);
    /* Never silently replace unreadable or malformed existing data. */
    FILE *probe = fopen(path, "r");
    if (probe) {
        fclose(probe);
        if (!clinic_load(&c, path)) { fprintf(stderr, "Cannot load %s; data left unchanged.\n", path); return EXIT_FAILURE; }
        puts("Saved clinic loaded.");
    } else if (errno != ENOENT) {
        fprintf(stderr, "Cannot open %s.\n", path); return EXIT_FAILURE;
    }
    puts("Smart Clinic Queue & Triage | 1=critical, 2=urgent, 3=priority, 4=normal");
    bool running = true; int result = EXIT_SUCCESS;
    while (running) {
        puts("\n1 Register   2 Check in   3 Start next consultation   4 Complete consultation\n"
             "5 Mark no-show   6 Undo latest check-in   7 Find ID   8 Find exact name\n"
             "9 Reports   10 Visit history   11 Save   12 View queue   0 Save and exit");
        uint64_t choice, id, severity, age;
        if (!read_number("Choice: ", &choice)) { if (feof(stdin)) break; continue; }
        Patient *p; char name[NAME_LEN];
        switch (choice) {
        case 0: running = false; break;
        case 1:
            if (read_line("Name: ", name, sizeof name) && read_number("Age (0-150): ", &age)) {
                p = age <= 150 ? clinic_register(&c, name, (unsigned)age) : NULL;
                if (p) { puts("Registered:"); print_patient(&c, p); }
                else puts("Registration failed: invalid name/age or insufficient memory.");
            }
            break;
        case 2:
            if (read_number("Patient ID: ", &id) && read_number("Severity (1-4): ", &severity))
                puts(severity <= 4 && clinic_checkin(&c, id, (unsigned)severity, time(NULL)) ? "Checked in." : "Check-in failed.");
            break;
        case 3:
            p = clinic_next(&c);
            if (p) print_patient(&c, p); else puts("Queue empty or a consultation is already active.");
            break;
        case 4: puts(clinic_complete(&c, time(NULL)) ? "Consultation completed." : "Cannot complete consultation."); break;
        case 5:
            if (read_number("Patient ID: ", &id)) puts(clinic_no_show(&c, id, time(NULL)) ? "Marked no-show." : "Patient must be waiting.");
            break;
        case 6: puts(clinic_undo(&c) ? "Check-in undone." : "No eligible operation at stack top (ineligible entry discarded)."); break;
        case 7:
            if (read_number("Patient ID: ", &id)) {
                p = table_find(&c, id); if (p) print_patient(&c, p); else puts("Patient not found.");
            }
            break;
        case 8:
            if (read_line("Exact name (case-sensitive): ", name, sizeof name)) {
                size_t count; Patient **matches = clinic_patients(&c, &count);
                if (!matches) { puts("Out of memory."); break; }
                size_t found = tree_search(c.names, name, matches, count);
                for (size_t i = 0; i < found; ++i) print_patient(&c, matches[i]);
                if (!found) puts("Patient not found.");
                free(matches);
            }
            break;
        case 9: report(&c); break;
        case 10: history(&c); break;
        case 11: puts(clinic_save(&c, path) ? "Saved." : "Save failed; check path/permissions or stale .tmp file."); break;
        case 12: show_queue(&c); break;
        default: puts("Unknown choice."); break;
        }
    }
    if (!clinic_save(&c, path)) { fprintf(stderr, "Save failed for %s.\n", path); result = EXIT_FAILURE; }
    else puts("Saved. Goodbye.");
    clinic_free(&c); return result;
}
