#include "clinic.h"
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>

static unsigned checks, suites;
#define CHECK(expr) do { ++checks; if (!(expr)) { \
    fprintf(stderr, "%s:%d: FAILED: %s\n", __FILE__, __LINE__, #expr); exit(EXIT_FAILURE); \
} } while (0)
static Patient *reg(Clinic *c, const char *name) {
    Patient *p = clinic_register(c, name, 30); CHECK(p); return p;
}
static void registration_and_indexes(void) {
    Clinic c; clinic_init(&c);
    CHECK(!clinic_register(&c, "", 30)); CHECK(!clinic_register(&c, "  ", 30));
    CHECK(!clinic_register(&c, "Bad|Name", 30)); CHECK(!clinic_register(&c, "Bad\nName", 30));
    CHECK(!clinic_register(&c, "A", 151)); CHECK(!clinic_register(&c, NULL, 30));
    char long_name[NAME_LEN + 1]; memset(long_name, 'x', NAME_LEN); long_name[NAME_LEN] = 0;
    CHECK(!clinic_register(&c, long_name, 30));
    Patient *a = reg(&c, "Mira"), *b = reg(&c, "Mira");
    reg(&c, "Aaron"); reg(&c, "Zoe"); reg(&c, "Nora"); reg(&c, "Mira");
    Patient *matches[4];
    CHECK(tree_search(c.names, "Mira", matches, 4) == 3);
    CHECK(matches[0] == a && matches[1] == b);
    CHECK(tree_search(c.names, "Mira", NULL, 0) == 3);
    CHECK(tree_search(c.names, "Missing", matches, 4) == 0);
    CHECK(tree_search(c.names, "Aaron", matches, 4) == 1);
    CHECK(tree_search(c.names, "Nora", matches, 4) == 1);
    CHECK(tree_search(c.names, "Zoe", matches, 4) == 1);
    CHECK(tree_search(c.names, "mira", matches, 4) == 0);
    for (unsigned i = 0; i < 300; ++i) {
        char name[40]; snprintf(name, sizeof name, "Patient %03u", i);
        Patient *p = reg(&c, name); CHECK(table_find(&c, p->id) == p);
    }
    CHECK(c.patient_count == 306);
    for (uint64_t i = 1; i <= 306; ++i) CHECK(table_find(&c, i)->id == i);
    CHECK(c.buckets[1] && c.buckets[1]->hash_next); CHECK(!table_find(&c, 99999));
    c.next_id = UINT64_MAX; CHECK(!clinic_register(&c, "Overflow", 1));
    clinic_free(&c); ++suites;
}
static void heap_and_fifo(void) {
    Heap h = {0}; Queue q = {0}; Patient p[257] = {{0}};
    CHECK(!heap_pop(&h)); CHECK(!heap_remove(&h, 1)); CHECK(!queue_pop(&q)); CHECK(!queue_remove(&q, 1));
    for (size_t i = 0; i < 257; ++i) {
        p[i].id = i + 1; p[i].severity = (unsigned)((i * 17) % 3) + 1; p[i].order = 257 - i;
        CHECK(heap_push(&h, &p[i])); CHECK(queue_push(&q, &p[i]));
    }
    CHECK(heap_remove(&h, 129)); CHECK(!heap_remove(&h, 129));
    Patient *last = NULL, *current;
    size_t popped = 0;
    while ((current = heap_pop(&h))) {
        if (last) CHECK(!patient_before(current, last));
        CHECK(current->id != 129); last = current; ++popped;
    }
    CHECK(popped == 256); heap_free(&h);
    CHECK(queue_remove(&q, 1)); CHECK(queue_remove(&q, 129)); CHECK(queue_remove(&q, 257));
    for (uint64_t id = 2; id < 257; ++id) {
        if (id == 129) continue;
        CHECK(queue_pop(&q)->id == id);
    }
    CHECK(q.size == 0 && !q.head && !q.tail);
    CHECK(queue_push(&q, &p[0])); CHECK(queue_pop(&q) == &p[0]); queue_free(&q);
    /* Exercise arbitrary heap removals and verify the heap invariant each time. */
    for (size_t i = 0; i < 257; ++i) CHECK(heap_push(&h, &p[i]));
    for (size_t i = 0; i < 257; ++i) {
        CHECK(heap_remove(&h, (i * 73) % 257 + 1));
        for (size_t j = 1; j < h.size; ++j) CHECK(!patient_before(h.items[j], h.items[(j - 1) / 2]));
    }
    heap_free(&h); ++suites;
}
static void workflow(void) {
    Clinic c; clinic_init(&c);
    Patient *normal = reg(&c, "Normal"), *urgent = reg(&c, "Urgent"), *critical = reg(&c, "Critical");
    Patient *critical2 = reg(&c, "Critical 2"), *normal2 = reg(&c, "Normal 2");
    CHECK(!clinic_checkin(&c, 999, 1, 100)); CHECK(!clinic_checkin(&c, normal->id, 0, 100));
    CHECK(!clinic_checkin(&c, normal->id, 5, 100)); CHECK(!clinic_checkin(&c, normal->id, 1, (time_t)-1));
    CHECK(clinic_wait_minutes(&c, normal->id) == SIZE_MAX);
    CHECK(!clinic_complete(&c, 100)); CHECK(!clinic_next(&c)); CHECK(!clinic_undo(&c));
    CHECK(clinic_checkin(&c, normal->id, 4, 100)); CHECK(!clinic_checkin(&c, normal->id, 3, 100));
    CHECK(clinic_checkin(&c, urgent->id, 2, 101)); CHECK(clinic_checkin(&c, critical->id, 1, 102));
    CHECK(clinic_checkin(&c, critical2->id, 1, 103)); CHECK(clinic_checkin(&c, normal2->id, 4, 104));
    CHECK(clinic_wait_minutes(&c, critical->id) == 0);
    CHECK(clinic_wait_minutes(&c, critical2->id) == 15);
    CHECK(clinic_wait_minutes(&c, urgent->id) == 30);
    CHECK(clinic_wait_minutes(&c, normal->id) == 45);
    CHECK(clinic_wait_minutes(&c, normal2->id) == 60);
    CHECK(!clinic_no_show(&c, normal2->id, 99));
    CHECK(clinic_no_show(&c, normal2->id, 110)); CHECK(normal2->status == NO_SHOW);
    CHECK(!clinic_undo(&c)); CHECK(normal2->status == NO_SHOW);
    CHECK(clinic_next(&c) == critical); CHECK(!clinic_next(&c));
    CHECK(!clinic_checkin(&c, critical->id, 1, 110)); CHECK(!clinic_no_show(&c, critical->id, 110));
    CHECK(!clinic_complete(&c, 99)); CHECK(c.active == critical);
    CHECK(clinic_wait_minutes(&c, critical2->id) == 15);
    CHECK(clinic_complete(&c, 120)); CHECK(critical->status == COMPLETED);
    CHECK(clinic_next(&c) == critical2); CHECK(clinic_complete(&c, 121));
    CHECK(clinic_next(&c) == urgent); CHECK(clinic_complete(&c, 122));
    CHECK(clinic_next(&c) == normal); CHECK(clinic_complete(&c, 123));
    CHECK(!clinic_next(&c));
    size_t visits = 0;
    Visit *prev = NULL;
    for (Visit *v = c.history_head; v; v = v->next) { CHECK(v->prev == prev); prev = v; ++visits; }
    CHECK(visits == 5 && prev == c.history_tail);
    for (Visit *v = c.history_tail; v; v = v->prev) --visits;
    CHECK(visits == 0);
    CHECK(clinic_checkin(&c, critical->id, 4, 200));
    CHECK(clinic_undo(&c)); CHECK(critical->status == COMPLETED && critical->severity == 1);
    CHECK(critical->checked_in == 102 && critical->order == c.history_head->next->order);
    CHECK(clinic_checkin(&c, normal2->id, 3, 201)); CHECK(clinic_undo(&c));
    CHECK(normal2->status == NO_SHOW && normal2->severity == 4);
    c.next_order = UINT64_MAX; CHECK(!clinic_checkin(&c, normal2->id, 3, 202));
    clinic_free(&c); ++suites;
}
static void undo_visits(void) {
    Clinic c; clinic_init(&c);
    Patient *a = reg(&c, "A"), *b = reg(&c, "B");
    CHECK(clinic_checkin(&c, a->id, 1, 100)); CHECK(clinic_undo(&c));
    CHECK(a->status == REGISTERED && !a->order && !a->severity && !a->checked_in);
    CHECK(clinic_checkin(&c, a->id, 4, 101));
    CHECK(clinic_checkin(&c, b->id, 4, 102)); CHECK(clinic_undo(&c));
    CHECK(c.normal.size == 1 && b->status == REGISTERED);
    CHECK(clinic_next(&c) == a); CHECK(clinic_complete(&c, 103));
    CHECK(clinic_checkin(&c, a->id, 2, 104)); CHECK(clinic_undo(&c));
    CHECK(a->status == COMPLETED && a->order == c.history_head->order);
    CHECK(!clinic_undo(&c)); CHECK(a->status == COMPLETED);
    clinic_free(&c); ++suites;
}
static void sorts(void) {
    Patient p[100] = {{0}}; Patient *a[100], *b[100];
    for (size_t i = 0; i < 100; ++i) {
        p[i].id = 100 - i; p[i].severity = (unsigned)(i % 4) + 1;
        snprintf(p[i].name, NAME_LEN, "Name %02zu", (i * 37) % 15);
    }
    for (ReportKey key = REPORT_NAME; key <= REPORT_SEVERITY; ++key) {
        for (size_t i = 0; i < 100; ++i) a[i] = b[i] = &p[i];
        CHECK(report_merge_sort(a, 100, key)); report_insertion_sort(b, 100, key);
        for (size_t i = 0; i < 100; ++i) {
            CHECK(a[i] == b[i]);
            if (!i) continue;
            Patient *x = a[i - 1], *y = a[i];
            if (key == REPORT_ID) CHECK(x->id < y->id);
            if (key == REPORT_NAME) CHECK(strcmp(x->name, y->name) <= 0);
            if (key == REPORT_SEVERITY) CHECK(x->severity <= y->severity);
        }
    }
    CHECK(report_merge_sort(NULL, 0, REPORT_NAME)); report_insertion_sort(NULL, 0, REPORT_ID);
    CHECK(report_merge_sort(a, 1, REPORT_NAME)); ++suites;
}
static void dsa_edges(void) {
    Clinic c; clinic_init(&c);
    CHECK(!c.history_head && !c.history_tail);
    CHECK(tree_search(NULL, "Nobody", NULL, 0) == 0);
    Patient *a = reg(&c, "Equal"), *b = reg(&c, "Zulu"), *d = reg(&c, "Equal");
    reg(&c, "Alpha"); reg(&c, "Equal");
    Patient *limited[2] = {NULL, b};
    CHECK(tree_search(c.names, "Equal", limited, 1) == 3);
    CHECK(limited[0] == a && limited[1] == b); /* no write past capacity */
    CHECK(tree_search(c.names, "Equal", NULL, 0) == 3);
    CHECK(clinic_checkin(&c, a->id, 4, 100));
    CHECK(queue_remove(&c.normal, a->id));
    CHECK(c.normal.size == 0 && !c.normal.head && !c.normal.tail);
    /* Restore the deliberately isolated queue removal before domain operations. */
    CHECK(queue_push(&c.normal, a));
    CHECK(!queue_remove(&c.normal, 999)); CHECK(c.normal.size == 1);
    CHECK(clinic_next(&c) == a); CHECK(clinic_complete(&c, 110));
    CHECK(c.history_head == c.history_tail);
    CHECK(!c.history_head->prev && !c.history_head->next);
    CHECK(clinic_checkin(&c, a->id, 1, 120));
    CHECK(clinic_undo(&c)); CHECK(a->status == COMPLETED && a->order == 1);
    CHECK(!clinic_undo(&c)); /* stale original check-in cannot undo a completed visit */
    CHECK(clinic_checkin(&c, a->id, 1, 121));
    CHECK(clinic_checkin(&c, d->id, 1, 122));
    CHECK(clinic_undo(&c)); CHECK(d->status == REGISTERED); CHECK(c.urgent.size == 1);
    CHECK(clinic_undo(&c)); CHECK(c.urgent.size == 0);
    CHECK(clinic_checkin(&c, a->id, 3, 123)); CHECK(clinic_next(&c) == a);
    CHECK(c.urgent.size == 0); CHECK(!heap_pop(&c.urgent));
    CHECK(!clinic_undo(&c)); CHECK(a->status == CONSULTING);
    CHECK(clinic_complete(&c, 130));
    clinic_free(&c);
    /* Explicitly force three IDs into the same collision chain. */
    Patient chain[3] = {{.id = 1}, {.id = 128}, {.id = 255}};
    Clinic table; clinic_init(&table);
    for (size_t i = 0; i < 3; ++i) table_insert(&table, &chain[i]);
    CHECK(table.buckets[1] == &chain[2]);
    CHECK(chain[2].hash_next == &chain[1] && chain[1].hash_next == &chain[0]);
    for (size_t i = 0; i < 3; ++i) CHECK(table_find(&table, chain[i].id) == &chain[i]);
    CHECK(!table_find(&table, 382)); /* miss in a populated bucket */
    /* table contains stack-owned fixtures, so it must not call clinic_free. */
    clinic_init(&c);
    for (unsigned i = 0; i < 1024; ++i) reg(&c, "Repeated");
    CHECK(tree_search(c.names, "Repeated", NULL, 0) == 1024);
    CHECK(tree_search(c.names, "Zzz", NULL, 0) == 0);
    clinic_free(&c); /* iterative cleanup of a maximally skewed tree */
    Patient equal[4] = {{0}}; Patient *items[4];
    for (size_t i = 0; i < 4; ++i) {
        equal[i].id = 10; equal[i].severity = 2; strcpy(equal[i].name, "Tie");
    }
    for (ReportKey key = REPORT_NAME; key <= REPORT_SEVERITY; ++key) {
        for (size_t i = 0; i < 4; ++i) items[i] = &equal[i];
        CHECK(report_merge_sort(items, 4, key));
        for (size_t i = 0; i < 4; ++i) CHECK(items[i] == &equal[i]);
        report_insertion_sort(items, 4, key);
        for (size_t i = 0; i < 4; ++i) CHECK(items[i] == &equal[i]);
    }
    /* Reverse-sorted and already-sorted independent expected order. */
    for (size_t i = 0; i < 4; ++i) { equal[i].id = 4 - i; items[i] = &equal[i]; }
    report_insertion_sort(items, 4, REPORT_ID);
    for (size_t i = 0; i < 4; ++i) CHECK(items[i]->id == i + 1);
    CHECK(report_merge_sort(items, 4, REPORT_ID));
    for (size_t i = 0; i < 4; ++i) CHECK(items[i]->id == i + 1);
    ++suites;
}
static void write_file(const char *path, const char *text) {
    FILE *f = fopen(path, "w"); CHECK(f); CHECK(fputs(text, f) >= 0); CHECK(!fclose(f));
}
static void persistence(void) {
    const char *path = "build/test-clinic.db";
    remove(path); remove("build/test-clinic.db.tmp");
    Clinic c, restored; clinic_init(&c); clinic_init(&restored);
    CHECK(clinic_save(&c, path)); CHECK(clinic_load(&restored, path)); CHECK(!restored.patient_count);
    Patient *a = reg(&c, "A"), *b = reg(&c, "B"), *d = reg(&c, "D"), *e = reg(&c, "E");
    CHECK(clinic_checkin(&c, a->id, 2, 100)); CHECK(clinic_next(&c) == a); CHECK(clinic_complete(&c, 110));
    CHECK(clinic_checkin(&c, b->id, 4, 111)); CHECK(clinic_no_show(&c, b->id, 112));
    CHECK(clinic_checkin(&c, a->id, 3, 113)); CHECK(clinic_next(&c) == a);
    CHECK(clinic_checkin(&c, d->id, 4, 114)); CHECK(clinic_checkin(&c, b->id, 4, 115));
    CHECK(clinic_checkin(&c, e->id, 1, 116));
    reg(&c, "Registered");
    CHECK(clinic_save(&c, path)); CHECK(clinic_save(&c, path)); CHECK(clinic_load(&restored, path));
    CHECK(restored.patient_count == 5 && restored.next_id == c.next_id && restored.next_order == c.next_order);
    CHECK(restored.active->id == a->id && restored.active->status == CONSULTING);
    CHECK(!restored.undo); CHECK(!clinic_next(&restored)); CHECK(clinic_complete(&restored, 120));
    CHECK(clinic_next(&restored)->id == e->id); CHECK(clinic_complete(&restored, 121));
    CHECK(clinic_next(&restored)->id == d->id); CHECK(clinic_complete(&restored, 122));
    CHECK(clinic_next(&restored)->id == b->id); CHECK(clinic_complete(&restored, 123));
    CHECK(!clinic_next(&restored)); CHECK(clinic_save(&restored, path)); CHECK(clinic_load(&c, path));
    CHECK(c.history_head->outcome == COMPLETED && c.history_head->next->outcome == NO_SHOW);
    CHECK(clinic_save(&c, path));
    write_file("build/test-clinic.db.tmp", "existing temp"); CHECK(!clinic_save(&c, path));
    CHECK(clinic_load(&restored, path)); remove("build/test-clinic.db.tmp");
    CHECK(!clinic_save(&c, "build/does-not-exist/file")); CHECK(!clinic_load(&c, "build/does-not-exist/file"));
    CHECK(!clinic_save(&c, NULL)); CHECK(!clinic_load(&c, NULL));
    const char *bad[] = {
        "", "CLINIC0|1|1\nEND\n", "CLINIC1|1|1\n", "CLINIC1|0|1\nEND\n",
        "CLINIC1|18446744073709551616|1\nEND\n", "CLINIC1|-1|1\nEND\n",
        "CLINIC1|1|1\nEND\njunk\n", "CLINIC1|2|2\nP|1|A|30|5|1|1|100\nEND\n",
        "CLINIC1|2|2\nP|1|A|30|1|9|1|100\nEND\n",
        "CLINIC1|2|2\nP|1|A|30|1|1|1|100\nP|1|B|30|0|0|0|0\nEND\n",
        "CLINIC1|1|2\nP|1|A|30|1|1|1|100\nEND\n",
        "CLINIC1|2|1\nP|1|A|30|1|1|1|100\nEND\n",
        "CLINIC1|3|3\nP|1|A|30|1|2|1|100\nP|2|B|30|1|2|2|100\nEND\n",
        "CLINIC1|3|3\nP|1|A|30|1|1|1|100\nP|2|B|30|1|1|1|100\nEND\n",
        "CLINIC1|2|2\nP|1|A|30|1|3|1|100\nEND\n",
        "CLINIC1|2|2\nP|1|A|30|0|0|0|0\nV|1|1|1|3|100|110\nEND\n",
        "CLINIC1|2|2\nP|1|A|30|1|3|1|100\nV|1|1|1|3|100|99\nEND\n",
        "CLINIC1|2|2\nP|1|A|30|1|3|1|100\nV|2|1|1|3|100|110\nEND\n",
        "CLINIC1|2|2\nP|1|A|30|1|3|1|100\nV|1|1|1|3|100|110\nV|1|1|1|3|100|110\nEND\n",
        "CLINIC1|2|2\nP|1|A|30|1|3|1|100\nV|1|1|2|3|100|110\nEND\n"
    };
    for (size_t i = 0; i < sizeof bad / sizeof *bad; ++i) {
        write_file(path, bad[i]); Patient *original = table_find(&c, 1);
        CHECK(!clinic_load(&c, path)); CHECK(table_find(&c, 1) == original); CHECK(c.patient_count == 5);
    }
    /* File order is deliberately different from queue order. */
    write_file(path, "CLINIC1|4|4\nP|3|C|30|4|1|2|100\nP|1|A|30|4|1|3|100\nP|2|B|30|4|1|1|100\nEND\n");
    CHECK(clinic_load(&c, path)); CHECK(clinic_next(&c)->id == 2); CHECK(clinic_complete(&c, 110));
    CHECK(clinic_next(&c)->id == 3); CHECK(clinic_complete(&c, 110)); CHECK(clinic_next(&c)->id == 1);
    clinic_free(&c); clinic_free(&restored); remove(path); ++suites;
}
int main(void) {
    registration_and_indexes(); heap_and_fifo(); workflow(); undo_visits(); sorts(); dsa_edges(); persistence();
    printf("PASS: %u suites, %u checks\n", suites, checks); return EXIT_SUCCESS;
}
