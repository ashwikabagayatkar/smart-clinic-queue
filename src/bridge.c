#include "clinic.h"
#include "bridge.h"
#include <inttypes.h>
#include <stdarg.h>
#include <stdlib.h>
#include <string.h>

typedef struct { Clinic clinic; char *path; } App;
typedef struct { char *data; size_t size, capacity; bool ok; } Json;
static void put(Json *j, const char *format, ...) {
    if (!j->ok) return;
    va_list args, copy;
    va_start(args, format); va_copy(copy, args);
    int count = vsnprintf(NULL, 0, format, copy); va_end(copy);
    if (count < 0 || (size_t)count > SIZE_MAX - j->size - 1) j->ok = false;
    if (j->ok && j->size + (size_t)count + 1 > j->capacity) {
        size_t capacity = j->size + (size_t)count + 1;
        if (capacity <= SIZE_MAX / 2) capacity *= 2;
        char *data = realloc(j->data, capacity);
        if (!data) j->ok = false;
        else { j->data = data; j->capacity = capacity; }
    }
    if (j->ok) {
        vsnprintf(j->data + j->size, j->capacity - j->size, format, args);
        j->size += (size_t)count;
    }
    va_end(args);
}
static void quote(Json *j, const char *s) {
    put(j, "\"");
    for (const unsigned char *p = (const unsigned char *)s; *p; ++p) {
        if (*p == '"' || *p == '\\') put(j, "\\%c", *p);
        else if (*p < 32) put(j, "\\u%04x", (unsigned)*p);
        else put(j, "%c", *p);
    }
    put(j, "\"");
}
static void patient_json(Json *j, const Clinic *c, const Patient *p) {
    put(j, "{\"id\":\"%" PRIu64 "\",\"name\":", p->id); quote(j, p->name);
    put(j, ",\"age\":%u,\"severity\":", p->age);
    if (p->status == AWAITING_TRIAGE) put(j, "null"); else put(j, "%u", p->severity);
    put(j, ",\"status\":");
    quote(j, status_name(p->status));
    put(j, ",\"needs_review\":%s", p->needs_review ? "true" : "false");
    put(j, ",\"order\":\"%" PRIu64 "\",\"checked_in\":%jd,\"wait\":", p->order, (intmax_t)p->checked_in);
    size_t wait = clinic_wait_minutes(c, p->id);
    if (wait == SIZE_MAX) put(j, "null"); else put(j, "%zu", wait);
    put(j, "}");
}
/* Clone ownership, indexes, queues, history and undo before a durable mutation.
   No pointer in the clone refers to an original Patient or container node. */
static bool clone_clinic(const Clinic *source, Clinic *dest) {
    clinic_init(dest);
    for (size_t b = 0; b < HASH_BUCKETS; ++b) {
        for (Patient *p = source->buckets[b]; p; p = p->hash_next) {
            Patient *copy = malloc(sizeof *copy);
            if (!copy) goto fail;
            *copy = *p; copy->hash_next = NULL;
            if (!tree_insert(&dest->names, copy)) { free(copy); goto fail; }
            table_insert(dest, copy);
        }
    }
    dest->next_id = source->next_id; dest->next_order = source->next_order;
    for (size_t i = 0; i < source->urgent.size; ++i)
        if (!heap_push(&dest->urgent, table_find(dest, source->urgent.items[i]->id))) goto fail;
    for (QueueNode *n = source->normal.head; n; n = n->next)
        if (!queue_push(&dest->normal, table_find(dest, n->patient->id))) goto fail;
    if (source->active) dest->active = table_find(dest, source->active->id);
    for (Visit *v = source->history_head; v; v = v->next) {
        Visit *copy = malloc(sizeof *copy);
        if (!copy) goto fail;
        *copy = *v; history_append(dest, copy);
    }
    Undo **tail = &dest->undo;
    for (Undo *u = source->undo; u; u = u->next) {
        *tail = malloc(sizeof **tail);
        if (!*tail) goto fail;
        **tail = *u; (*tail)->next = NULL; tail = &(*tail)->next;
    }
    return true;
fail:
    clinic_free(dest); return false;
}
static char *snapshot(App *app, bool ok, const char *message, unsigned action,
                      uint64_t id, const char *name, unsigned key, unsigned algorithm) {
    Clinic *c = &app->clinic;
    Json j = {.ok = true};
    size_t count;
    Patient **a = clinic_patients(c, &count);
    if (!a) return NULL;
    if (action == 11 && algorithm == 2) report_insertion_sort(a, count, (ReportKey)key);
    else if (!report_merge_sort(a, count, action == 11 ? (ReportKey)key : REPORT_ID)) { free(a); return NULL; }
    put(&j, "{\"ok\":%s,\"message\":", ok ? "true" : "false"); quote(&j, message);
    put(&j, ",\"state\":{\"patients\":[");
    for (size_t i = 0; i < count; ++i) { if (i) put(&j, ","); patient_json(&j, c, a[i]); }
    put(&j, "],\"queue\":[");
    /* Use the real heap extraction algorithm on an independent pointer copy. */
    Heap heap = {0};
    if (c->urgent.size) {
        heap.items = malloc(c->urgent.size * sizeof *heap.items);
        if (!heap.items) { free(a); free(j.data); return NULL; }
        memcpy(heap.items, c->urgent.items, c->urgent.size * sizeof *heap.items);
        heap.size = heap.capacity = c->urgent.size;
    }
    size_t queued = 0, critical = 0, urgent = 0;
    Patient *p;
    while ((p = heap_pop(&heap))) {
        if (queued++) put(&j, ",");
        patient_json(&j, c, p);
        if (p->severity == 1) ++critical;
        if (p->severity == 2) ++urgent;
    }
    heap_free(&heap);
    for (QueueNode *n = c->normal.head; n; n = n->next) {
        if (queued++) put(&j, ",");
        patient_json(&j, c, n->patient);
    }
    put(&j, "],\"active\":");
    if (c->active) patient_json(&j, c, c->active); else put(&j, "null");
    put(&j, ",\"history\":[");
    size_t visits = 0, completed = 0, missed = 0;
    for (Visit *v = c->history_head; v; v = v->next) {
        if (visits++) put(&j, ",");
        if (v->outcome == COMPLETED) ++completed; else ++missed;
        put(&j, "{\"patient_id\":\"%" PRIu64 "\",\"order\":\"%" PRIu64 "\",\"name\":", v->patient_id, v->order);
        quote(&j, table_find(c, v->patient_id)->name);
        put(&j, ",\"severity\":%u,\"outcome\":", v->severity); quote(&j, status_name(v->outcome));
        put(&j, ",\"checked_in\":%jd,\"ended\":%jd}", (intmax_t)v->checked_in, (intmax_t)v->ended);
    }
    put(&j, "],\"stats\":{\"patients\":%zu,\"waiting\":%zu,\"critical\":%zu,\"urgent\":%zu,"
        "\"completed\":%zu,\"no_show\":%zu,\"visits\":%zu},\"next_id\":\"%" PRIu64 "\",\"can_undo\":",
        count, queued, critical, urgent, completed, missed, visits, c->next_id);
    bool can_undo = false;
    for (Undo *u = c->undo; u; u = u->next) {
        p = table_find(c, u->patient_id);
        if (p && p->status == WAITING && p->order == u->order) { can_undo = true; break; }
    }
    put(&j, "%s},\"matches\":[", can_undo ? "true" : "false");
    size_t found = 0;
    if (action == 9) { p = table_find(c, id); if (p) { a[0] = p; found = 1; } }
    if (action == 10) found = tree_search(c->names, name, a, count);
    for (size_t i = 0; i < found; ++i) { if (i) put(&j, ","); patient_json(&j, c, a[i]); }
    put(&j, "]}"); free(a);
    if (!j.ok) { free(j.data); return NULL; }
    return j.data;
}
void *app_open(const char *path) {
    if (!path || !*path) return NULL;
    App *app = calloc(1, sizeof *app);
    if (!app) return NULL;
    clinic_init(&app->clinic);
    app->path = malloc(strlen(path) + 1);
    if (!app->path) { free(app); return NULL; }
    strcpy(app->path, path);
    /* The host creates an initial empty snapshot; failure is never an empty reset. */
    if (!clinic_load(&app->clinic, path)) { app_close(app); return NULL; }
    return app;
}
void app_close(void *context) {
    App *app = context;
    if (app) { clinic_free(&app->clinic); free(app->path); free(app); }
}
void app_release(char *text) { free(text); }
char *app_call(void *context, unsigned action, const char *name, uint64_t id,
               unsigned age, unsigned severity, unsigned key, unsigned algorithm) {
    App *app = context;
    if (!app || !name || action > 16 || key > REPORT_SEVERITY || algorithm < 1 || algorithm > 2) return NULL;
    Clinic *c = &app->clinic, backup;
    const char *message = "Up to date";
    bool ok = true, mutation = (action >= 1 && action <= 6) || action >= 12;
    bool cloned = false;
    if (mutation) {
        cloned = clone_clinic(c, &backup);
        if (!cloned) return snapshot(app, false, "Not enough memory. Nothing changed.", 0, 0, "", 0, 1);
    }
    switch (action) {
    case 1: case 12: {
        Patient *p = clinic_register(c, name, age, severity);
        ok = p != NULL;
        if (ok && action == 12) ok = clinic_checkin(c, p->id, p->severity, time(NULL));
        message = ok ? "Patient registered" : "Registration failed. Check name, age and staff-assigned severity (1–4).";
        break;
    }
    case 13: ok = clinic_register_pending(c, name, age) != NULL; message = ok ? "Patient registered; awaiting staff triage" : "Invalid registration."; break;
    case 15: ok = clinic_require_review(c, id); message = ok ? "Patient awaits assessment review" : "Patient is already waiting or consulting."; break;
    case 14: ok = clinic_review_checkin(c, id, severity, time(NULL)); message = ok ? "Explicit priority assigned; patient checked in" : "Patient cannot be queued in the current state."; break;
    case 16: ok = clinic_reprioritize(c, id, severity); message = ok ? "Waiting priority updated; arrival order preserved" : "Only a waiting patient can be reprioritized (1–4)."; break;
    case 2: ok = clinic_checkin(c, id, severity, time(NULL)); message = ok ? "Patient checked in" : "Check-in requires an existing, non-waiting patient and severity 1–4."; break;
    case 3: ok = clinic_next(c) != NULL; message = ok ? "Consultation started" : "Queue is empty or a consultation is already active."; break;
    case 4: ok = clinic_complete(c, time(NULL)); message = ok ? "Consultation completed" : "No consultation can be completed."; break;
    case 5: ok = clinic_no_show(c, id, time(NULL)); message = ok ? "Patient marked as no-show" : "Only a waiting patient can be marked as no-show."; break;
    case 6:
        ok = false;
        while (c->undo && !ok) ok = clinic_undo(c);
        message = ok ? "Latest eligible check-in undone" : "No eligible waiting check-in to undo."; break;
    case 7: ok = clinic_save(c, app->path); message = ok ? "Snapshot saved" : "Save failed. Check permissions, space and stale .tmp files."; break;
    case 8: ok = clinic_load(c, app->path); message = ok ? "Snapshot reloaded; undo history reset" : "Load failed. Current data is unchanged; check for legacy severity 0 or a corrupt snapshot."; break;
    case 9: case 10: message = "Search complete"; break;
    case 11: message = "Report generated in C"; break;
    default: break;
    }
    if (mutation && ok && !clinic_save(c, app->path)) {
        ok = false; message = "Autosave failed. The operation was rolled back. Check disk space, permissions or stale .tmp files.";
    }
    if (cloned) {
        if (ok) clinic_free(&backup);
        else { clinic_free(c); *c = backup; }
    }
    return snapshot(app, ok, message, action, id, name, key, algorithm);
}

void *app_checkpoint(void *context) {
    App *app = context;
    Clinic *copy = malloc(sizeof *copy);
    if (!app || !copy) { free(copy); return NULL; }
    if (!clone_clinic(&app->clinic, copy)) { free(copy); return NULL; }
    return copy;
}
void app_discard_checkpoint(void *checkpoint) {
    Clinic *copy = checkpoint;
    if (copy) { clinic_free(copy); free(copy); }
}
void app_restore_checkpoint(void *context, void *checkpoint) {
    App *app = context; Clinic *copy = checkpoint;
    if (!app || !copy) return;
    clinic_free(&app->clinic); app->clinic = *copy; free(copy);
}
