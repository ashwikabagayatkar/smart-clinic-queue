#include "bridge.h"
#include <assert.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
static char *call(void *app, unsigned action, const char *name, uint64_t id, unsigned severity) {
    char *json = app_call(app, action, name, id, 30, severity, 0, 1);
    assert(json); return json;
}
int main(void) {
    const char *path = "build/test-bridge.db";
    remove(path); remove("build/test-bridge.db.tmp");
    FILE *f = fopen(path, "w"); assert(f);
    assert(fputs("CLINIC1|1|1\nEND\n", f) >= 0); assert(!fclose(f));
    void *app = app_open(path); assert(app);
    char *json = call(app, 12, "Fictional \"Quoted\"", 0, 4);
    assert(strstr(json, "\"ok\":true")); assert(strstr(json, "\\\"Quoted\\\"")); app_release(json);
    json = call(app, 12, "Critical Fictional", 0, 1); assert(strstr(json,"\"critical\":1")); app_release(json);
    json = call(app, 3, "", 0, 0); assert(strstr(json,"Consulting")); app_release(json);
    f = fopen("build/test-bridge.db.tmp", "w"); assert(f); assert(!fclose(f));
    json = call(app, 6, "", 0, 0); assert(strstr(json,"rolled back")); assert(strstr(json,"\"can_undo\":true")); app_release(json);
    remove("build/test-bridge.db.tmp");
    json = call(app, 6, "", 0, 0); assert(strstr(json,"\"ok\":true")); app_release(json);
    json = call(app, 4, "", 0, 0); assert(strstr(json,"\"completed\":1")); app_release(json);
    app_close(app); app = app_open(path); assert(app);
    json = call(app, 0, "", 0, 0); assert(strstr(json,"\"can_undo\":false")); assert(strstr(json,"\"completed\":1")); app_release(json);
    json = call(app, 13, "Patient-entered Fictional", 0, 0);
    assert(strstr(json,"\"severity\":null")); assert(strstr(json,"Awaiting triage")); app_release(json);
    void *checkpoint = app_checkpoint(app); assert(checkpoint);
    json = call(app, 14, "", 3, 3); assert(strstr(json,"\"needs_review\":false")); app_release(json);
    app_restore_checkpoint(app, checkpoint);
    json = call(app, 0, "", 0, 0); assert(strstr(json,"Awaiting triage")); assert(strstr(json,"\"severity\":null")); app_release(json);
    checkpoint = app_checkpoint(app); assert(checkpoint); app_discard_checkpoint(checkpoint);
    json = call(app, 7, "", 0, 0); assert(strstr(json,"\"ok\":true")); app_release(json);
    app_close(app); app = app_open(path); assert(app);
    json = call(app, 0, "", 0, 0); assert(strstr(json,"Awaiting triage")); app_release(json);
    app_close(app); remove(path);
    puts("PASS: C bridge lifecycle, JSON escaping, transactional undo rollback and restart");
    return EXIT_SUCCESS;
}
