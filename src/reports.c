#include "clinic.h"
#include <stdlib.h>
#include <string.h>
static int compare(const Patient *a, const Patient *b, ReportKey key) {
    if (key == REPORT_NAME) {
        int cmp = strcmp(a->name, b->name);
        if (cmp) return cmp;
    } else if (key == REPORT_SEVERITY && a->severity != b->severity)
        return a->severity < b->severity ? -1 : 1;
    return (a->id > b->id) - (a->id < b->id);
}
void report_insertion_sort(Patient **a, size_t n, ReportKey key) {
    for (size_t i = 1; i < n; ++i) {
        Patient *p = a[i]; size_t j = i;
        while (j && compare(a[j - 1], p, key) > 0) { a[j] = a[j - 1]; --j; }
        a[j] = p;
    }
}
static void merge(Patient **a, Patient **tmp, size_t lo, size_t hi, ReportKey key) {
    if (hi - lo < 2) return;
    size_t mid = lo + (hi - lo) / 2;
    merge(a, tmp, lo, mid, key); merge(a, tmp, mid, hi, key);
    size_t l = lo, r = mid, k = lo;
    while (l < mid && r < hi)
        tmp[k++] = compare(a[l], a[r], key) <= 0 ? a[l++] : a[r++];
    while (l < mid) tmp[k++] = a[l++];
    while (r < hi) tmp[k++] = a[r++];
    for (k = lo; k < hi; ++k) a[k] = tmp[k];
}
bool report_merge_sort(Patient **a, size_t n, ReportKey key) {
    if (n < 2) return true;
    if (n > SIZE_MAX / sizeof *a) return false;
    Patient **tmp = malloc(n * sizeof *tmp);
    if (!tmp) return false;
    merge(a, tmp, 0, n, key); free(tmp); return true;
}
