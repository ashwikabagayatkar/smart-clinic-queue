#include "clinic.h"
#include <ctype.h>
#include <stdlib.h>
#include <string.h>
void clinic_init(Clinic *c) { *c = (Clinic){.next_id = 1, .next_order = 1}; }
void clinic_free(Clinic *c) {
    heap_free(&c->urgent); queue_free(&c->normal); tree_free(c->names);
    undo_free(c->undo);
    Visit *v = c->history_head;
    while (v) { Visit *next = v->next; free(v); v = next; }
    for (size_t i = 0; i < HASH_BUCKETS; ++i) {
        Patient *p = c->buckets[i];
        while (p) { Patient *next = p->hash_next; free(p); p = next; }
    }
    clinic_init(c);
}
const char *status_name(Status s) {
    static const char *const names[] = {"Registered", "Waiting", "Consulting", "Completed", "No-show"};
    return s >= REGISTERED && s <= NO_SHOW ? names[s] : "Invalid";
}
Patient *clinic_register(Clinic *c, const char *name, unsigned age) {
    if (!name || !*name || strlen(name) >= NAME_LEN || age > 150 || c->next_id == UINT64_MAX) return NULL;
    bool visible = false;
    for (const unsigned char *s = (const unsigned char *)name; *s; ++s) {
        if (iscntrl(*s) || *s == '|') return NULL;
        if (!isspace(*s)) visible = true;
    }
    if (!visible) return NULL;
    Patient *p = calloc(1, sizeof *p);
    if (!p) return NULL;
    p->id = c->next_id; p->age = age; p->status = REGISTERED;
    strcpy(p->name, name);
    if (!tree_insert(&c->names, p)) { free(p); return NULL; }
    table_insert(c, p); ++c->next_id; return p;
}
bool clinic_checkin(Clinic *c, uint64_t id, unsigned severity, time_t now) {
    Patient *p = table_find(c, id);
    if (!p || p->status == WAITING || p->status == CONSULTING || severity < 1 || severity > 4 ||
        now < 0 || c->next_order == UINT64_MAX) return false;
    if (!undo_push(c, p)) return false;
    uint64_t old_order = p->order;
    unsigned old_severity = p->severity;
    p->order = c->next_order; p->severity = severity;
    bool ok = severity < 4 ? heap_push(&c->urgent, p) : queue_push(&c->normal, p);
    if (!ok) {
        p->order = old_order; p->severity = old_severity;
        Undo *u = c->undo; c->undo = u->next; free(u); return false;
    }
    /* The stack records the new visit identity as well as the previous state. */
    c->undo->order = p->order;
    p->checked_in = now; p->status = WAITING; ++c->next_order; return true;
}
Patient *clinic_next(Clinic *c) {
    if (c->active) return NULL;
    Patient *p = c->urgent.size ? heap_pop(&c->urgent) : queue_pop(&c->normal);
    if (p) { p->status = CONSULTING; c->active = p; }
    return p;
}
static bool finish(Clinic *c, Patient *p, Status outcome, time_t now) {
    if (now < p->checked_in) return false;
    Visit *v = calloc(1, sizeof *v);
    if (!v) return false;
    *v = (Visit){.patient_id = p->id, .order = p->order, .severity = p->severity,
        .outcome = outcome, .checked_in = p->checked_in, .ended = now};
    if (p->status == WAITING) {
        bool removed = p->severity < 4 ? heap_remove(&c->urgent, p->id) : queue_remove(&c->normal, p->id);
        if (!removed) { free(v); return false; }
    }
    p->status = outcome; history_append(c, v); return true;
}
bool clinic_complete(Clinic *c, time_t now) {
    if (!c->active || !finish(c, c->active, COMPLETED, now)) return false;
    c->active = NULL; return true;
}
bool clinic_no_show(Clinic *c, uint64_t id, time_t now) {
    Patient *p = table_find(c, id);
    return p && p->status == WAITING && finish(c, p, NO_SHOW, now);
}
bool clinic_undo(Clinic *c) {
    Undo *u = c->undo;
    if (!u) return false;
    Patient *p = table_find(c, u->patient_id);
    /* Consume ineligible entries as well: undo never rewinds consultation/history. */
    c->undo = u->next;
    bool ok = p && p->status == WAITING && p->order == u->order;
    if (ok) {
        ok = p->severity < 4 ? heap_remove(&c->urgent, p->id) : queue_remove(&c->normal, p->id);
        if (ok) {
            p->status = u->previous_status; p->severity = u->previous_severity;
            p->checked_in = u->previous_checkin;
            p->order = u->previous_order;
        }
    }
    free(u); return ok;
}
size_t clinic_wait_minutes(const Clinic *c, uint64_t id) {
    Patient *p = table_find(c, id);
    if (!p || p->status != WAITING) return SIZE_MAX;
    size_t ahead = c->active ? 1 : 0;
    for (size_t i = 0; i < c->urgent.size; ++i)
        if (p->severity == 4 || patient_before(c->urgent.items[i], p)) ++ahead;
    if (p->severity == 4)
        for (QueueNode *n = c->normal.head; n && n->patient != p; n = n->next) ++ahead;
    return ahead > SIZE_MAX / CONSULT_MINUTES ? SIZE_MAX : ahead * CONSULT_MINUTES;
}
Patient **clinic_patients(const Clinic *c, size_t *count) {
    *count = c->patient_count;
    if (c->patient_count > SIZE_MAX / sizeof(Patient *)) return NULL;
    Patient **a = malloc((c->patient_count ? c->patient_count : 1) * sizeof *a);
    if (!a) return NULL;
    size_t n = 0;
    for (size_t i = 0; i < HASH_BUCKETS; ++i)
        for (Patient *p = c->buckets[i]; p; p = p->hash_next) a[n++] = p;
    return a;
}
