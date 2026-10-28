#ifndef CLINIC_H
#define CLINIC_H
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <time.h>
#define NAME_LEN 80
#define HASH_BUCKETS 127
#define CONSULT_MINUTES 15

typedef enum { REGISTERED, WAITING, CONSULTING, COMPLETED, NO_SHOW } Status;
typedef struct Patient {
    uint64_t id, order;
    char name[NAME_LEN];
    unsigned age, severity;
    Status status;
    time_t checked_in;
    struct Patient *hash_next;
} Patient;
typedef struct QueueNode { Patient *patient; struct QueueNode *next; } QueueNode;
typedef struct { QueueNode *head, *tail; size_t size; } Queue;
typedef struct { Patient **items; size_t size, capacity; } Heap;
typedef struct NameNode { Patient *patient; struct NameNode *left, *right; } NameNode;
typedef struct Visit {
    uint64_t patient_id, order;
    unsigned severity;
    Status outcome;
    time_t checked_in, ended;
    struct Visit *prev, *next;
} Visit;
typedef struct Undo {
    uint64_t patient_id, order, previous_order;
    Status previous_status;
    unsigned previous_severity;
    time_t previous_checkin;
    struct Undo *next;
} Undo;
typedef struct {
    Patient *buckets[HASH_BUCKETS];
    size_t patient_count;
    uint64_t next_id, next_order;
    Heap urgent;
    Queue normal;
    NameNode *names;
    Visit *history_head, *history_tail;
    Undo *undo;
    Patient *active;
} Clinic;
typedef enum { REPORT_NAME, REPORT_ID, REPORT_SEVERITY } ReportKey;

/* Data structures own nodes/storage, but never the Patient objects. */
bool patient_before(const Patient *a, const Patient *b);
bool heap_push(Heap *heap, Patient *patient);
Patient *heap_pop(Heap *heap);
bool heap_remove(Heap *heap, uint64_t id);
void heap_free(Heap *heap);
bool queue_push(Queue *queue, Patient *patient);
Patient *queue_pop(Queue *queue);
bool queue_remove(Queue *queue, uint64_t id);
void queue_free(Queue *queue);
Patient *table_find(const Clinic *clinic, uint64_t id);
void table_insert(Clinic *clinic, Patient *patient);
bool tree_insert(NameNode **root, Patient *patient);
size_t tree_search(const NameNode *root, const char *name, Patient **out, size_t capacity);
void tree_free(NameNode *root);
void history_append(Clinic *clinic, Visit *visit);
bool undo_push(Clinic *clinic, const Patient *patient);
void undo_free(Undo *undo);
bool report_merge_sort(Patient **items, size_t count, ReportKey key);
void report_insertion_sort(Patient **items, size_t count, ReportKey key);

void clinic_init(Clinic *clinic);
void clinic_free(Clinic *clinic);
const char *status_name(Status status);
Patient *clinic_register(Clinic *clinic, const char *name, unsigned age);
bool clinic_checkin(Clinic *clinic, uint64_t id, unsigned severity, time_t now);
Patient *clinic_next(Clinic *clinic);
bool clinic_complete(Clinic *clinic, time_t now);
bool clinic_no_show(Clinic *clinic, uint64_t id, time_t now);
bool clinic_undo(Clinic *clinic);
/* Returns SIZE_MAX for a patient who is not waiting. */
size_t clinic_wait_minutes(const Clinic *clinic, uint64_t id);
Patient **clinic_patients(const Clinic *clinic, size_t *count);
/* Atomic replacement on save; failed loads leave the current clinic intact.
   Undo is session-local and deliberately not persisted. */
bool clinic_save(const Clinic *clinic, const char *path);
bool clinic_load(Clinic *clinic, const char *path);
#endif
