/* Experimental 4.1K N-RAW full-height path. Appended code; D10 addresses stay fixed.
 * Stock runtime: kind=1, nominal=4, actual=8, size=4, rate=4, request=4;
 * original driver=15, frontend plan=11. Full-height half-readout uses the
 * native 2756-row physical geometry, 2752 active rows and logical extent 2760.
 * TICO/physical sensor equivalence remains unqualified. Emulator input only.
 */
#define OG_STATE 0xA0FF6F000
#define OG_FLAG 0xA03D5C02B
.text
.balign 16
/* x0 snapshot -> w0 predicate. x9/x10 clobbered, no other registers. */
.global og4k_wanted_hook
og4k_wanted_hook:
    ldr x9, =OG_FLAG
    ldrb w9, [x9]
    cmp w9, #1
    b.ne 9f
    ldr w9, [x0]
    cmp w9, #1
    b.ne 9f
    ldr w9, [x0, #0x388]
    cmp w9, #4
    b.ne 9f
    ldr w9, [x0, #0x38c]
    cmp w9, #4
    b.ne 9f
    ldr w9, [x0, #0x390]
    sub w9, w9, #4
    cmp w9, #2
    b.hi 9f
    ldr w9, [x0, #0x3a0]
    cmp w9, #4
    b.ne 9f
    ldr x9, =0xA03D5C014
    ldr w9, [x9]
    cmp w9, #6
    b.ne 9f
    mov w0, #1
    ret
9:  mov w0, wzr
    ret

.global og4k_configuration_hook
og4k_configuration_hook:
    tbz w0, #0, 9f
    stp x8, x9, [sp, #-48]!
    stp x10, x11, [sp, #16]
    stp x0, x30, [sp, #32]
    mov x0, x19
    bl og4k_wanted_hook
    mov w8, w0
    ldp x0, x30, [sp, #32]
    cbz w8, 8f
    mov w20, w0
    /* Preserve the common full-height marker used by the D10 display seams.
     * This mode actually consumes readout8; its physical dimensions are below. */
    mov w11, #5520
    ldr x9, =0xA02A979EE
    strh w11, [x9]
    ldr x9, =0xA02A979C2
    strh w11, [x9]
    ldr x9, =0xA02A97CDA
    strh w11, [x9]
    strh w11, [x9, #4]
    mov w11, #5504
    ldr x9, =0xA02A97A1A
    strh w11, [x9]
    mov w11, #2756
    ldr x9, =0xA02A979D2
    strh w11, [x9]
    ldr x9, =0xA02A979FE
    strh w11, [x9]
    ldr x9, =0xA02A97D12
    strh w11, [x9]
    strh w11, [x9, #4]
    mov w11, #2752
    ldr x9, =0xA02A97A2A
    strh w11, [x9]
    ldr x9, =OG_STATE
    mov w11, #1
    str w11, [x9]
    ldr w11, [x9, #4]
    cbz w11, 1f
    str w11, [x9, #0x10]
1:  str wzr, [x9, #4]
    dsb ishst
    ldp x10, x11, [sp, #16]
    ldp x8, x9, [sp], #48
    b original_40F79390
8:  ldp x10, x11, [sp, #16]
    ldp x8, x9, [sp], #48
9:  b legacy_configuration_hook

/* Full-height frontend for plan11 as well as D10's view plan10. */
.global og4k_half_plan_hook
og4k_half_plan_hook:
    ldr w9, [x20]
    cmp w9, #11
    b.ne 9f
    ldr w9, [x20, #4]
    cmp w9, #4
    b.ne 9f
    ldr x9, =OG_STATE
    ldr w9, [x9]
    cbz w9, 9f
    mov w9, #2756
    mov x1, #0x74a0
    b original_41062078
9:  b legacy_half_plan_hook

/* Common store tail, after the native plan11 geometry has been emitted.
 * Proxy rasters remain unchanged; preserve all scratch registers and NZCV. */
.global og4k_geometry_hook
og4k_geometry_hook:
    stp x8, x9, [sp, #-48]!
    stp x10, x11, [sp, #16]
    mrs x8, nzcv
    str x8, [sp, #32]
    ldr x8, =OG_STATE
    ldr w9, [x8]
    cbz w9, 9f
    ldr x8, =OG_FLAG
    ldrb w9, [x8]
    cmp w9, #1
    b.ne 9f
    ldr x8, =0xA03D5C014
    ldr w9, [x8]
    cmp w9, #6
    b.ne 9f
    ldr x8, =0xA03BB71D8
    ldr w9, [x8]
    cmp w9, #4
    b.ne 9f
    ldr w9, [x8, #4]
    sub w9, w9, #4
    cmp w9, #2
    b.hi 9f
    ldrh w8, [x19, #0x48]
    mov w9, #4140
    cmp w8, w9
    b.ne 9f
    ldrh w8, [x19, #0x4a]
    cmp w8, #2344
    b.ne 9f
    ldrh w8, [x19, #0xc]
    mov w9, #4128
    cmp w8, w9
    b.ne 9f
    ldrh w8, [x19, #0xe]
    cmp w8, #2322
    b.ne 9f
    mov w8, #2752
    strh w8, [x19, #0xe]
    mov w8, #2756
    strh w8, [x19, #0x4a]
    strh w8, [x19, #0x4e]
    mov w8, #2
    strh w8, [x19, #0x16]
    strh w8, [x19, #0x5e]
    mov w8, #2760
    strh w8, [x19, #0x66]
9:  ldr x8, [sp, #32]
    msr nzcv, x8
    ldp x10, x11, [sp, #16]
    ldp x8, x9, [sp], #48
    strh w10, [x19, #0x68]
    b original_410665F8

/* Original 4.1K Tenc inner size branch at 41066A70: width already 4140.
 * Use a physical-height-bounded coded raster; do not borrow view extent2760. */
/* This candidate encoded height is a lab hypothesis until TICO and metadata
 * paths are qualified; this unit is never exposed by the production builder. */
.global og4k_inner_hook
og4k_inner_hook:
    mov w9, #2330
    stp x10, x11, [sp, #-32]!
    mrs x10, nzcv
    str x10, [sp, #16]
    ldr x10, =OG_STATE
    ldr w11, [x10]
    cbz w11, 1f
    ldr x10, =OG_FLAG
    ldrb w11, [x10]
    cmp w11, #1
    b.ne 1f
    ldr x10, =0xA03D5C014
    ldr w11, [x10]
    cmp w11, #6
    b.ne 1f
    ldr x10, =0xA03BB71D8
    ldr w11, [x10]
    cmp w11, #4
    b.ne 1f
    ldr w11, [x10, #4]
    sub w11, w11, #4
    cmp w11, #2
    b.hi 1f
    ldr w11, [x0, #0x20]
    cmp w11, #4
    b.ne 1f
    mov w11, #4140
    cmp w8, w11
    b.ne 1f
    mov w9, #2756
1:  ldr x10, [sp, #16]
    msr nzcv, x10
    ldp x10, x11, [sp], #32
    b original_41066A74

.ltorg

/* The three lab rows follow the three preserved 8.3K open-gate rows.
 * Main-menu summary reuses the native 4.1K rate/quality image resources. */
.balign 16
.global og4k_menu_summary_match_hook
og4k_menu_summary_match_hook:
    ldur w3, [x20, #-0xc]
    mov w8, #0x35c3
    sub w8, w3, w8
    cmp w8, #2
    b.hi 9f
    cmp w26, #6
    b.ne 9f
    ldr x9, =OG_FLAG
    ldrb w9, [x9]
    cmp w9, #1
    b.ne 8f
    add w8, w8, #9
    mov w9, #12
    umaddl x8, w8, w9, x24
    cmp w23, #1
    b.ne 1f
    ldr w1, [x8, #4]
    b original_40572EF0
1:  ldr w1, [x8, #8]
    b original_40572EF0
8:  b original_40572EF0
9:  b legacy_menu_summary_match_hook
.ltorg

/* Stock N-RAW 30p reaches driver variant2, bypassing D10's variant3 hook.
 * Gate at the shared original leaf entry, preserving every non-lab call. */
.balign 16
.global og4k_driver_entry_hook
og4k_driver_entry_hook:
    mov x8, x0
    ldr w9, [x8]
    cmp w9, #5
    b.ne 9f
    ldr w9, [x8, #4]
    cmp w9, #8
    b.ne 9f
    ldr w9, [x8, #0xc]
    sub w9, w9, #2
    cmp w9, #1
    b.hi 9f
    ldr x9, =OG_STATE
    ldr w9, [x9]
    cbz w9, 9f
    ldr x9, =OG_FLAG
    ldrb w9, [x9]
    cmp w9, #1
    b.ne 9f
    ldr x9, =0xA03D5C014
    ldr w9, [x9]
    cmp w9, #6
    b.ne 9f
    ldr x9, =0xA03BB71D8
    ldr w10, [x9]
    cmp w10, #4
    b.ne 9f
    ldr w10, [x9, #4]
    sub w10, w10, #4
    cmp w10, #2
    b.hi 9f
    ldr x9, =0xA02A979FE
    ldrh w10, [x9]
    cmp w10, #2756
    b.ne 9f
    mov w0, #14
    ret
9:  b original_411717F8
.ltorg
