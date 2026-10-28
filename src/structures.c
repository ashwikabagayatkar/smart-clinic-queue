#include "clinic.h"
#include <stdlib.h>
#include <string.h>

bool patient_before(const Patient *a, const Patient *b) {
    return a->severity < b->severity ||
        (a->severity == b->severity && a->order < b->order);
}
static void swap(Patient **a, Patient **b) { Patient *t = *a; *a = *b; *b = t; }
static void sift_down(Heap *h, size_t i) {
    for (;;) {
        size_t best = i, left = i * 2 + 1, right = left + 1;
        if (left < h->size && patient_before(h->items[left], h->items[best])) best = left;
        if (right < h->size && patient_before(h->items[right], h->items[best])) best = right;
        if (best == i) break;
        swap(&h->items[i], &h->items[best]); i = best;
    }
}
bool heap_push(Heap *h, Patient *p) {
    if (h->size == h->capacity) {
        size_t cap = h->capacity ? h->capacity * 2 : 16;
        if (cap < h->capacity || cap > SIZE_MAX / sizeof *h->items) return false;
        Patient **items = realloc(h->items, cap * sizeof *items);
        if (!items) return false;
        h->items = items; h->capacity = cap;
    }
    size_t i = h->size++;
    h->items[i] = p;
    while (i && patient_before(h->items[i], h->items[(i - 1) / 2])) {
        size_t parent = (i - 1) / 2;
        swap(&h->items[i], &h->items[parent]); i = parent;
    }
    return true;
}
Patient *heap_pop(Heap *h) {
    if (!h->size) return NULL;
    Patient *p = h->items[0];
    h->items[0] = h->items[--h->size];
    if (h->size) sift_down(h, 0);
    return p;
}
bool heap_remove(Heap *h, uint64_t id) {
    size_t i = 0;
    while (i < h->size && h->items[i]->id != id) ++i;
    if (i == h->size) return false;
    h->items[i] = h->items[--h->size];
    if (i < h->size) {
        while (i && patient_before(h->items[i], h->items[(i - 1) / 2])) {
            size_t parent = (i - 1) / 2;
            swap(&h->items[i], &h->items[parent]); i = parent;
        }
        sift_down(h, i);
    }
    return true;
}
void heap_free(Heap *h) { free(h->items); *h = (Heap){0}; }
bool queue_push(Queue *q, Patient *p) {
    QueueNode *n = malloc(sizeof *n);
    if (!n) return false;
    *n = (QueueNode){p, NULL};
    if (q->tail) q->tail->next = n; else q->head = n;
    q->tail = n; ++q->size; return true;
}
Patient *queue_pop(Queue *q) {
    if (!q->head) return NULL;
    QueueNode *n = q->head; Patient *p = n->patient;
    q->head = n->next; if (!q->head) q->tail = NULL;
    free(n); --q->size; return p;
}
bool queue_remove(Queue *q, uint64_t id) {
    QueueNode *prev = NULL, *n = q->head;
    while (n && n->patient->id != id) { prev = n; n = n->next; }
    if (!n) return false;
    if (prev) prev->next = n->next; else q->head = n->next;
    if (q->tail == n) q->tail = prev;
    free(n); --q->size; return true;
}
void queue_free(Queue *q) { while (queue_pop(q)) {} }
Patient *table_find(const Clinic *c, uint64_t id) {
    for (Patient *p = c->buckets[id % HASH_BUCKETS]; p; p = p->hash_next)
        if (p->id == id) return p;
    return NULL;
}
void table_insert(Clinic *c, Patient *p) {
    size_t b = p->id % HASH_BUCKETS;
    p->hash_next = c->buckets[b]; c->buckets[b] = p; ++c->patient_count;
}
bool tree_insert(NameNode **root, Patient *p) {
    while (*root) {
        int cmp = strcmp(p->name, (*root)->patient->name);
        root = cmp < 0 ? &(*root)->left : &(*root)->right;
    }
    *root = malloc(sizeof **root);
    if (!*root) return false;
    **root = (NameNode){p, NULL, NULL}; return true;
}
size_t tree_search(const NameNode *root, const char *name, Patient **out, size_t cap) {
    size_t found = 0;
    while (root) {
        int cmp = strcmp(name, root->patient->name);
        if (cmp < 0) root = root->left;
        else {
            if (!cmp) { if (found < cap) out[found] = root->patient; ++found; }
            root = root->right;
        }
    }
    return found;
}
void tree_free(NameNode *root) {
    /* Iterative rotations avoid recursion on a degenerate name tree. */
    while (root) {
        if (root->left) {
            NameNode *left = root->left;
            root->left = left->right; left->right = root; root = left;
        } else { NameNode *next = root->right; free(root); root = next; }
    }
}
void history_append(Clinic *c, Visit *v) {
    v->prev = c->history_tail; v->next = NULL;
    if (c->history_tail) c->history_tail->next = v; else c->history_head = v;
    c->history_tail = v;
}
bool undo_push(Clinic *c, const Patient *p) {
    Undo *u = malloc(sizeof *u);
    if (!u) return false;
    *u = (Undo){p->id, p->order, p->order, p->status, p->severity, p->checked_in, p->needs_review, c->undo};
    c->undo = u; return true;
}
void undo_free(Undo *u) { while (u) { Undo *next = u->next; free(u); u = next; } }
