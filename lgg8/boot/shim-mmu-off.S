/* SPDX-License-Identifier: MIT */
/* Experimental ARM64 handoff. Requires an identity-mapped shim and payload. */
.section .text
.global _start
.global blocked
.global payload
_start:
    b entry
    .word 0
    .quad 0
    .quad PAYLOAD_SIZE + 4096
    .quad 0xa
    .quad 0, 0, 0
    .ascii "ARM\x64"
    .word 0

/* Check each 4 KiB interval, including both endpoints. PAR attributes are
 * outside bits [47:12]. Reject addresses above the supported 48-bit range. */
.macro check_mapping address
    lsr x14, \address, #48
    cbnz x14, blocked
    cmp x20, #2
    b.eq .Lel2\@
    at s1e1r, \address
    b .Ltranslated\@
.Lel2\@:
    at s1e2r, \address
.Ltranslated\@:
    isb
    mrs x14, par_el1
    tbnz x14, #0, blocked
    ubfx x15, x14, #12, #36
    ubfx x16, \address, #12, #36
    cmp x15, x16
    b.ne blocked
.endm

/* Verify stage 1 identity translation and write permission on destination */
.macro check_mapping_write address
    lsr x14, \address, #48
    cbnz x14, blocked
    cmp x20, #2
    b.eq .Lw_el2\@
    at s1e1w, \address
    b .Lw_translated\@
.Lw_el2\@:
    at s1e2w, \address
.Lw_translated\@:
    isb
    mrs x14, par_el1
    tbnz x14, #0, blocked
    ubfx x15, x14, #12, #36
    ubfx x16, \address, #12, #36
    cmp x15, x16
    b.ne blocked
.endm

entry:
    mrs x20, CurrentEL
    lsr x20, x20, #2
    cmp x20, #1
    b.eq check_shim
    cmp x20, #2
    b.ne blocked
check_shim:
    adr x17, _start
    check_mapping x17
    add x17, x17, #4095
    check_mapping x17

    adr x11, destination
    ldr w5, [x11]
    ldr w13, [x11, #4]
    orr x5, x5, x13, lsl #32
    adr x11, length
    ldr w6, [x11]
    ldr w13, [x11, #4]
    orr x6, x6, x13, lsl #32
    cbz x6, blocked
    adds x18, x5, x6
    b.cs blocked
    adr x11, device_tree
    ldr w7, [x11]
    ldr w13, [x11, #4]
    orr x7, x7, x13, lsl #32
    cmp x7, x5
    b.lo blocked
    cmp x7, x18
    b.hs blocked
    tst x7, #7
    b.ne blocked

    /* Check writable identity mapping of destination */
    mov x17, x5
check_destination:
    check_mapping_write x17
    add x17, x17, #4096
    cmp x17, x18
    b.lo check_destination
    sub x17, x18, #1
    check_mapping_write x17

    /* Check readable identity mapping of source payload */
    adr x4, payload
    add x19, x4, x6
check_source:
    check_mapping x4
    add x4, x4, #4096
    cmp x4, x19
    b.lo check_source
    sub x4, x19, #1
    check_mapping x4

    adr x4, payload
    adr x12, _start
    cmp x12, x18
    b.hs copy
    cmp x4, x5
    b.ls copy
    b blocked
copy:
    cmp x4, x5
    b.eq clean
    cmp x5, x4
    b.lo forward
    add x7, x4, x6
    cmp x5, x7
    b.hs forward
    add x4, x4, x6
    add x5, x5, x6
backward:
    ldr w2, [x4, #-4]!
    str w2, [x5, #-4]!
    subs x6, x6, #4
    b.ne backward
    b clean
forward:
    ldr w2, [x4], #4
    str w2, [x5], #4
    subs x6, x6, #4
    b.ne forward
clean:
    mrs x9, ctr_el0
    ubfx x9, x9, #16, #4
    mov x10, #4
    lsl x10, x10, x9
    adr x11, destination
    ldr w4, [x11]
    ldr w13, [x11, #4]
    orr x4, x4, x13, lsl #32
    mov x17, x4
clean_payload:
    dc cvac, x17
    add x17, x17, x10
    cmp x17, x18
    b.lo clean_payload
    adr x17, _start
    add x18, x17, #4096
clean_shim:
    dc cvac, x17
    add x17, x17, x10
    cmp x17, x18
    b.lo clean_shim
    dsb sy
    ic iallu
    dsb sy
    isb
    msr daifset, #0xf
    adr x11, device_tree
    ldr w0, [x11]
    ldr w13, [x11, #4]
    orr x0, x0, x13, lsl #32
    mov x1, xzr
    mov x2, xzr
    mov x3, xzr
    cmp x20, #2
    b.eq disable_el2
    mrs x9, sctlr_el1
    bic x9, x9, #1
    bic x9, x9, #4
    msr sctlr_el1, x9
    isb
    tlbi vmalle1
    dsb sy
    isb
    br x4
disable_el2:
    mrs x9, sctlr_el2
    bic x9, x9, #1
    bic x9, x9, #4
    msr sctlr_el2, x9
    isb
    tlbi alle2
    dsb sy
    isb
    br x4
blocked:
#ifdef DIAGNOSTIC_PSCI_RESET
    mov w0, #9
    movk w0, #0x8400, lsl #16
    mov x1, xzr
    mov x2, xzr
    mov x3, xzr
    smc #0
#endif
1:  wfe
    b 1b
.balign 8
destination: .quad LOAD_ADDRESS
device_tree: .quad DTB_ADDRESS
length: .quad PAYLOAD_SIZE
.org 4096
payload:
    .incbin PAYLOAD_PATH
