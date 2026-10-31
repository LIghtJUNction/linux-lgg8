/* SPDX-License-Identifier: GPL-2.0-only */
#ifndef TEST_FG_DMA_KERNEL_SHIM_H
#define TEST_FG_DMA_KERNEL_SHIM_H
#ifndef TEST_FG_DMA_KERNEL_OFFLINE
#error "This shim is for a standalone offline executable only"
#endif

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <errno.h>
#include <pthread.h>
#include <stdatomic.h>
#include <string.h>

typedef uint8_t u8;
typedef int64_t ktime_t;
#define __maybe_unused __attribute__((unused))
#define BIT(n) (1UL << (n))
#define ARRAY_SIZE(a) (sizeof(a) / sizeof((a)[0]))
#define IS_ERR_OR_NULL(p) (!(p) || (uintptr_t)(p) >= (uintptr_t)-4095)
#define WARN_ON_ONCE(c) test_kernel_warn(!!(c))

struct mutex {
    pthread_mutex_t native;
    bool held;
    pthread_t owner;
    atomic_uint attempts;
    unsigned int unlocks;
};

/* These are bus operation tags, not a second transaction implementation. */
enum test_io {
    T_MEM, T_INFO, T_PEEK, T_MODE, T_STATUS, T_PREFLIGHT_DMA,
    T_PREFLIGHT_ARB, T_STALE_GRANT, T_REQUEST_ARB, T_REQUEST_DMA,
    T_GRANT, T_DATA, T_RELEASE_DMA, T_RELEASE_ARB, T_VERIFY_DMA,
    T_VERIFY_ARB, T_IO_COUNT
};
struct test_fault { int rc; bool applied, drop; };
struct test_event {
    enum test_io tag;
    unsigned int reg, mask, value;
    size_t length;
};
struct regmap {
    struct mutex *lock;
    uint8_t regs[0x4900];
    int val_bytes, stride, grant_after;
    bool stale_grant, attempted;
    unsigned int polls, calls[T_IO_COUNT];
    struct test_fault faults[T_IO_COUNT];
    struct test_event events[128];
    size_t event_count;
    unsigned int format_calls;
    bool partial_data_error;
};

int test_kernel_warn(bool condition);
ktime_t ktime_get(void);
int ktime_compare(ktime_t a, ktime_t b);
void might_sleep(void);
void usleep_range(unsigned long lower, unsigned long upper);
int mutex_trylock(struct mutex *lock);
void mutex_unlock(struct mutex *lock);
int regmap_get_val_bytes(struct regmap *map);
int regmap_get_reg_stride(struct regmap *map);
int regmap_read_bypassed(struct regmap *map, unsigned int reg, unsigned int *val);
int regmap_write_bits(struct regmap *map, unsigned int reg,
                      unsigned int mask, unsigned int val);
int regmap_bulk_read(struct regmap *map, unsigned int reg, void *data, size_t size);
static inline int32_t sign_extend32(uint32_t value, int index)
{
    uint64_t mask = (1ULL << (index + 1)) - 1;
    int64_t low = (int64_t)(value & mask);

    return (int32_t)(low - ((value & (1U << index)) ? (1LL << (index + 1)) : 0));
}
#endif
