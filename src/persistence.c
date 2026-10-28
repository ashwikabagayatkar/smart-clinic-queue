#include "clinic.h"
#include <errno.h>
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>
#ifdef _WIN32
#include <windows.h>
#include <fcntl.h>
#include <io.h>
#include <sys/stat.h>
static wchar_t *wide_path(const char *path) {
    int count = MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, NULL, 0);
    if (count <= 0) return NULL;
    wchar_t *wide = malloc((size_t)count * sizeof *wide);
    if (!wide) return NULL;
    if (!MultiByteToWideChar(CP_UTF8, MB_ERR_INVALID_CHARS, path, -1, wide, count)) {
        free(wide); return NULL;
    }
    return wide;
}
static FILE *snapshot_open(const char *path, bool writing) {
    wchar_t *wide = wide_path(path);
    if (!wide) return NULL;
    FILE *file = NULL;
    if (writing) {
        /* _O_EXCL also works on older MSVCRT builds that lack fopen's C11 x mode. */
        int fd = _wopen(wide, _O_WRONLY | _O_CREAT | _O_EXCL | _O_TEXT, _S_IREAD | _S_IWRITE);
        if (fd >= 0) {
            file = _fdopen(fd, "w");
            if (!file) {
                int error = errno;
                _close(fd); _wremove(wide); errno = error;
            }
        }
    } else file = _wfopen(wide, L"r");
    free(wide); return file;
}
static bool snapshot_replace(const char *source, const char *dest) {
    wchar_t *from = wide_path(source), *to = wide_path(dest);
    bool ok = from && to && MoveFileExW(from, to, MOVEFILE_REPLACE_EXISTING | MOVEFILE_WRITE_THROUGH);
    free(from); free(to); return ok;
}
static void snapshot_remove(const char *path) {
    wchar_t *wide = wide_path(path);
    if (wide) { _wremove(wide); free(wide); }
}
#else
static FILE *snapshot_open(const char *path, bool writing) { return fopen(path, writing ? "wx" : "r"); }
static bool snapshot_replace(const char *source, const char *dest) { return rename(source, dest) == 0; }
static void snapshot_remove(const char *path) { (void)remove(path); }
#endif

bool clinic_save(const Clinic *c, const char *path) {
    if (!path || !*path || strlen(path) > SIZE_MAX - 5) return false;
    char *temp = malloc(strlen(path) + 5);
    if (!temp) return false;
    sprintf(temp, "%s.tmp", path);
    /* C11 exclusive creation avoids overwriting a pre-existing temporary file. */
    FILE *f = snapshot_open(temp, true);
    if (!f) { free(temp); return false; }
    bool ok = fprintf(f, "CLINIC2|%" PRIu64 "|%" PRIu64 "\n", c->next_id, c->next_order) > 0;
    size_t count;
    Patient **a = clinic_patients(c, &count);
    if (!a) ok = false;
    if (ok) ok = report_merge_sort(a, count, REPORT_ID);
    for (size_t i = 0; ok && i < count; ++i) {
        Patient *p = a[i];
        char priority[32];
        if (p->status == AWAITING_TRIAGE) strcpy(priority, "none");
        else snprintf(priority, sizeof priority, "%u", p->severity);
        ok = fprintf(f, "P|%" PRIu64 "|%s|%u|%s|%d|%" PRIu64 "|%jd|%u\n",
            p->id, p->name, p->age, priority, (int)p->status, p->order, (intmax_t)p->checked_in, p->needs_review ? 1u : 0u) > 0;
    }
    free(a);
    for (Visit *v = c->history_head; ok && v; v = v->next)
        ok = fprintf(f, "V|%" PRIu64 "|%" PRIu64 "|%u|%d|%jd|%jd\n", v->patient_id,
            v->order, v->severity, (int)v->outcome, (intmax_t)v->checked_in, (intmax_t)v->ended) > 0;
    if (ok) ok = fputs("END\n", f) >= 0;
    if (fclose(f)) ok = false;
    if (ok) ok = snapshot_replace(temp, path);
    if (!ok) snapshot_remove(temp);
    free(temp); return ok;
}
static bool number(const char *s, uint64_t *out) {
    if (!s || !*s) return false;
    for (const char *p = s; *p; ++p) if (*p < '0' || *p > '9') return false;
    errno = 0; char *end;
    uintmax_t value = strtoumax(s, &end, 10);
    if (errno || *end || value > UINT64_MAX) return false;
    *out = (uint64_t)value; return true;
}
static size_t fields(char *s, char **out, size_t capacity) {
    size_t n = 0;
    for (;;) {
        if (n == capacity) return 0;
        out[n++] = s;
        char *sep = strchr(s, '|');
        if (!sep) return n;
        *sep = '\0'; s = sep + 1;
    }
}
static bool timestamp(uint64_t value, time_t *out) {
    if (value > INTMAX_MAX) return false;
    *out = (time_t)value;
    return *out >= 0 && (uintmax_t)*out == value;
}
static bool parse_patient(Clinic *c, char **s, size_t n, bool supports_pending) {
    uint64_t id, age, severity, status, order, checked;
    if ((n != 8 && n != 9) || (!supports_pending && n != 8) || !number(s[1], &id) || !number(s[3], &age) || !number(s[5], &status) || !number(s[6], &order) || !number(s[7], &checked) ||
        !id || table_find(c, id) || age > 150 || status > AWAITING_TRIAGE) return false;
    bool pending = status == AWAITING_TRIAGE;
    if (pending) {
        if (!supports_pending || strcmp(s[4], "none")) return false;
        severity = UNASSIGNED_PRIORITY;
    } else if (!number(s[4], &severity) || severity < 1 || severity > 4) return false;
    uint64_t review = pending ? 1 : 0;
    if (n == 9 && (!number(s[8], &review) || review > 1)) return false;
    if ((status == WAITING || status == CONSULTING) && review) return false;
    time_t when;
    if (!timestamp(checked, &when)) return false;
    if ((status == REGISTERED || pending) ? (order || checked) : (!severity || !order)) return false;
    Patient *p = pending ? clinic_register_pending(c, s[2], (unsigned)age) : clinic_register(c, s[2], (unsigned)age, (unsigned)severity);
    if (!p) return false;
    /* clinic_register builds both indexes; move the new patient to its stored ID bucket. */
    size_t bucket = p->id % HASH_BUCKETS;
    c->buckets[bucket] = p->hash_next; --c->patient_count;
    p->id = id; p->severity = (unsigned)severity; p->status = (Status)status;
    p->order = order; p->checked_in = when; p->needs_review = review != 0; table_insert(c, p);
    if (p->status == CONSULTING) {
        if (c->active) return false;
        c->active = p;
    }
    return true;
}
static bool parse_visit(Clinic *c, char **s, size_t n) {
    uint64_t id, order, severity, outcome, checked, ended;
    if (n != 7 || !number(s[1], &id) || !number(s[2], &order) || !number(s[3], &severity) ||
        !number(s[4], &outcome) || !number(s[5], &checked) || !number(s[6], &ended) ||
        !table_find(c, id) || !order || severity < 1 || severity > 4 ||
        (outcome != COMPLETED && outcome != NO_SHOW) || ended < checked) return false;
    Visit *v = calloc(1, sizeof *v);
    if (!v) return false;
    if (!timestamp(checked, &v->checked_in) || !timestamp(ended, &v->ended)) { free(v); return false; }
    v->patient_id = id; v->order = order; v->severity = (unsigned)severity; v->outcome = (Status)outcome;
    for (Visit *old = c->history_head; old; old = old->next)
        if (old->order == order) { free(v); return false; }
    history_append(c, v); return true;
}
static bool restore_queues(Clinic *c, uint64_t next_id, uint64_t next_order) {
    size_t n;
    Patient **a = clinic_patients(c, &n);
    if (!a) return false;
    bool ok = next_id > 0 && next_order > 0;
    /* Insertion sort explicitly restores FIFO check-in order, independent of file order. */
    for (size_t i = 1; i < n; ++i) {
        Patient *p = a[i]; size_t j = i;
        while (j && a[j - 1]->order > p->order) { a[j] = a[j - 1]; --j; }
        a[j] = p;
    }
    for (size_t i = 0; ok && i < n; ++i) {
        Patient *p = a[i];
        if (p->id >= next_id || p->order >= next_order ||
            (i && p->order && p->order == a[i - 1]->order)) { ok = false; break; }
        Visit *latest = NULL;
        for (Visit *v = c->history_head; v; v = v->next) {
            if (v->order >= next_order) { ok = false; break; }
            if (v->patient_id == p->id) {
                if (v->order > p->order || (latest && latest->order >= v->order)) { ok = false; break; }
                latest = v;
            } else if (v->order == p->order && p->order) { ok = false; break; }
        }
        if (!ok) break;
        if (p->status == COMPLETED || p->status == NO_SHOW) {
            if (!latest || latest->order != p->order || latest->outcome != p->status ||
                latest->severity != p->severity || latest->checked_in != p->checked_in) { ok = false; break; }
        } else if (latest && latest->order >= p->order) { ok = false; break; }
        if (p->status == WAITING)
            ok = p->severity < 4 ? heap_push(&c->urgent, p) : queue_push(&c->normal, p);
    }
    free(a);
    if (ok) { c->next_id = next_id; c->next_order = next_order; }
    return ok;
}
bool clinic_load(Clinic *c, const char *path) {
    if (!path) return false;
    FILE *f = snapshot_open(path, false);
    if (!f) return false;
    Clinic loaded; clinic_init(&loaded);
    char line[512], *s[10]; uint64_t next_id = 0, next_order = 0;
    bool ok = false, ended = false, visits_started = false, supports_pending = false;
    if (fgets(line, sizeof line, f)) {
        char *nl = strchr(line, '\n');
        if (nl) {
            *nl = '\0';
            size_t n = fields(line, s, 10);
            supports_pending = n == 3 && !strcmp(s[0], "CLINIC2");
            ok = n == 3 && (!strcmp(s[0], "CLINIC1") || !strcmp(s[0], "CLINIC2")) && number(s[1], &next_id) && number(s[2], &next_order);
        }
    }
    while (ok && fgets(line, sizeof line, f)) {
        char *nl = strchr(line, '\n');
        if (!nl) { ok = false; break; }
        *nl = '\0';
        if (!strcmp(line, "END")) { ended = true; break; }
        size_t n = fields(line, s, 10);
        if (n && !strcmp(s[0], "P") && !visits_started) ok = parse_patient(&loaded, s, n, supports_pending);
        else if (n && !strcmp(s[0], "V")) { visits_started = true; ok = parse_visit(&loaded, s, n); }
        else ok = false;
    }
    if (!ended || fgetc(f) != EOF || ferror(f)) ok = false;
    if (fclose(f)) ok = false;
    if (ok) ok = restore_queues(&loaded, next_id, next_order);
    if (ok) { clinic_free(c); *c = loaded; } else clinic_free(&loaded);
    return ok;
}

bool clinic_file_present(const char *path, bool *present) {
    if (!path || !present) return false;
    FILE *file = snapshot_open(path, false);
    if (file) { *present = true; return fclose(file) == 0; }
    if (errno == ENOENT) { *present = false; return true; }
    return false;
}
