"""Compile the complete kernel transaction source with offline API shims.

CC selects the compiler; SMB5_INPUT_SANITIZER selects undefined (default) or thread.
"""

import os
from pathlib import Path
import subprocess
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]

SHIM = r"""
#ifndef SMB5_INPUT_HOST_SHIM
#define SMB5_INPUT_HOST_SHIM
#include <assert.h>
#include <errno.h>
#include <pthread.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdatomic.h>
#include <stdlib.h>
typedef uint32_t u32;
typedef uint64_t u64;
#define U32_MAX UINT32_MAX
#define GFP_KERNEL 0
struct mutex { pthread_mutex_t native; };
typedef struct { atomic_int value; } atomic_t;
/* Observe the value actually loaded; pausing must not replace or reload it. */
static void (*host_after_atomic_read)(const atomic_t *v, int value);
static inline void atomic_set(atomic_t *v, int value)
{ atomic_init(&v->value, value); }
static inline int atomic_read_acquire(const atomic_t *v)
{
    int value = atomic_load_explicit(&v->value, memory_order_acquire);
    if (host_after_atomic_read) host_after_atomic_read(v, value);
    return value;
}
static inline int atomic_xchg(atomic_t *v, int value)
{ return atomic_exchange_explicit(&v->value, value, memory_order_seq_cst); }
/* Host-only scheduling observation, never changes production logic. */
static void (*host_before_unlock)(struct mutex *lock);
static void (*host_before_lock)(struct mutex *lock);
static inline void mutex_init(struct mutex *lock)
{ assert(!pthread_mutex_init(&lock->native, NULL)); }
static inline int mutex_trylock(struct mutex *lock)
{
    int ret = pthread_mutex_trylock(&lock->native);
    assert(ret == 0 || ret == EBUSY);
    return ret == 0;
}
static inline void mutex_unlock(struct mutex *lock)
{
    if (host_before_unlock) host_before_unlock(lock);
    assert(!pthread_mutex_unlock(&lock->native));
}
static inline void mutex_lock(struct mutex *lock)
{
    if (host_before_lock) host_before_lock(lock);
    assert(!pthread_mutex_lock(&lock->native));
}
static inline void mutex_destroy(struct mutex *lock)
{ assert(!pthread_mutex_destroy(&lock->native)); }
static inline void *kzalloc(size_t bytes, int flags)
{ (void)flags; return calloc(1, bytes); }
#define kzalloc_obj(object) kzalloc(sizeof(object), GFP_KERNEL)
static inline void kfree(void *ptr) { free(ptr); }
#endif
"""


class Smb5InputTransactionTest(unittest.TestCase):
    def test_actual_kernel_source(self):
        compiler = os.environ.get("CC", "cc")
        sanitizer = os.environ.get("SMB5_INPUT_SANITIZER", "undefined")
        self.assertIn(sanitizer, ("undefined", "thread"))
        with tempfile.TemporaryDirectory(prefix="test-smb5-input-", dir=ROOT / "lgg8/tests") as temp:
            directory = Path(temp)
            headers = directory / "include/linux"
            headers.mkdir(parents=True)
            (headers.parent / "shim.h").write_text(SHIM)
            for name in ("types", "errno", "limits", "mutex", "slab", "atomic"):
                contents = '#include "../shim.h"\n'
                if name == "errno":
                    contents = '#include_next <linux/errno.h>\n' + contents
                (headers / f"{name}.h").write_text(contents)
            binary = directory / "test"
            env = {**os.environ, "TMPDIR": str(directory)}
            subprocess.run([
                compiler, "-pipe", "-std=gnu11", "-O2", "-Wall", "-Wextra", "-Werror", "-pthread",
                f"-fsanitize={sanitizer}", "-fno-sanitize-recover=all", "-I", str(headers.parent),
                str(ROOT / "lgg8/tests/test_smb5_input_transaction.c"), "-o", str(binary),
            ], check=True, env=env)
            subprocess.run([str(binary)], check=True, timeout=10, env=env)


if __name__ == "__main__":
    unittest.main()
