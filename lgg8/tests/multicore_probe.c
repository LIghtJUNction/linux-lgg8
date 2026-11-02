/* SPDX-License-Identifier: GPL-2.0-only */
/* Freestanding AArch64 scheduling probe: no device or persistent-file access. */
static long syscall3(long number, long a, long b, long c)
{
	register long x8 __asm__("x8") = number;
	register long x0 __asm__("x0") = a;
	register long x1 __asm__("x1") = b;
	register long x2 __asm__("x2") = c;

	__asm__ volatile("svc #0" : "+r"(x0) : "r"(x8), "r"(x1), "r"(x2)
			 : "memory", "cc");
	return x0;
}

static __attribute__((noreturn)) void finish(long status)
{
	syscall3(93, status, 0, 0);
	__builtin_unreachable();
}

void _start(void)
{
	for (unsigned int cpu = 0; cpu < 8; cpu++) {
		unsigned long mask = 1UL << cpu;
		unsigned int observed = ~0U;
		char line[] = "CPU0_OK\n";

		/* sched_setaffinity(0, sizeof(mask), &mask), then getcpu(). */
		if (syscall3(122, 0, sizeof(mask), (long)&mask))
			finish(10 + cpu);
		if (syscall3(168, (long)&observed, 0, 0) || observed != cpu)
			finish(30 + cpu);
		line[3] += cpu;
		if (syscall3(64, 1, (long)line, sizeof(line) - 1) != sizeof(line) - 1)
			finish(50 + cpu);
	}
	finish(0);
}
