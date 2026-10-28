#ifndef BRIDGE_H
#define BRIDGE_H
#include <stdint.h>
#ifdef _WIN32
#define CLINIC_EXPORT __declspec(dllexport)
#else
#define CLINIC_EXPORT
#endif
/* Opaque context; no C structure layout crosses the foreign-function boundary. */
CLINIC_EXPORT void *app_open(const char *path);
CLINIC_EXPORT void app_close(void *context);
/* Returns owned UTF-8 JSON; release using app_release, never the host allocator.
   Actions: 0 state, 1 register, 2 checkin, 3 next, 4 complete, 5 no-show,
   6 latest eligible undo, 7 save, 8 load, 9 ID search, 10 name search,
   11 reports, 12 register and check in; internal actions 13 pending registration,
   14 staff-reviewed check-in, 15 require review. Mutation successes are autosaved;
   failures restore the entire prior state, including undo. */
CLINIC_EXPORT char *app_call(void *context, unsigned action, const char *name,
                            uint64_t id, unsigned age, unsigned severity,
                            unsigned key, unsigned algorithm);
CLINIC_EXPORT void app_release(char *text);
/* Cross-file transaction support: checkpoint is owned, consumed on restore. */
CLINIC_EXPORT void *app_checkpoint(void *context);
CLINIC_EXPORT void app_discard_checkpoint(void *checkpoint);
CLINIC_EXPORT void app_restore_checkpoint(void *context, void *checkpoint);
#endif
