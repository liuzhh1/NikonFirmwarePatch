/* One native410A4FC4 invocation owns one48-byte stack capsule.
 * The direct height callback runs at depthD0; the crop callback at depth120
 * through6334(frame10) and6470(frame40). Native saved return addresses are
 * checked before reading our capsule. No global registry or source writes.
 */
#define COOKIE 0x4F47344B4E524D54
.text
.balign 16
.global og4k_nrmt_scope_hook
og4k_nrmt_scope_hook:
    stp x29, x30, [sp, #-48]!
    str x1, [sp, #16]
    ldr x8, =COOKIE
    str x8, [sp, #24]
    str xzr, [sp, #32]
    str w0, [sp, #40]
    str wzr, [sp, #44]
    cmp w0, #4
    b.ne scope_call
    cbz x1, scope_call
    cbz x3, scope_call
    ldr w8, [x1]
    cmp w8, #1
    b.ne scope_call
    ldr w8, [x1, #8]
    cmp w8, #8
    b.ne scope_call
    ldr w8, [x1, #0x388]
    cmp w8, #4
    b.ne scope_call
    ldr w8, [x1, #0x38c]
    cmp w8, #4
    b.ne scope_call
    ldr w9, [x1, #0x390]
    str w9, [sp, #32]
    sub w8, w9, #4
    cmp w8, #2
    b.hi scope_call
    ldr w8, [x1, #0x3a0]
    cmp w8, #4
    b.ne scope_call
    ldr x8, =0xA03D5C02B
    ldrb w8, [x8]
    cmp w8, #1
    b.ne scope_call
    ldr x8, =0xA03D5C014
    ldr w8, [x8]
    cmp w8, #6
    b.ne scope_call
    ldr x8, =0xA03BB71D8
    ldr w10, [x8]
    cmp w10, #4
    b.ne scope_call
    ldr w10, [x8, #4]
    cmp w10, w9
    b.ne scope_call
    ldr x8, =0xA0FF6F000
    ldr w8, [x8]
    cmp w8, #1
    b.ne scope_call
    ldr x8, =0xA02A979FE
    ldrh w8, [x8]
    cmp w8, #2756
    b.ne scope_call
    mov w8, #1
    str w8, [sp, #36]
scope_call:
    bl scope_original
.global og4k_nrmt_scope_return
og4k_nrmt_scope_return:
scope_return:
    stp xzr, xzr, [sp, #16]
    stp xzr, xzr, [sp, #32]
    ldp x29, x30, [sp], #48
    ret
scope_original:
    sub sp, sp, #0xd0              // exact replaced native prologue
    b original_410A4FC8

.macro save_check
    stp x16, x17, [sp, #-32]!
    mrs x16, nzcv
    str x16, [sp, #16]
.endm
.macro restore_check
    ldr x16, [sp, #16]
    msr nzcv, x16
    ldp x16, x17, [sp], #32
.endm
/* frame = our wrapperSP minus this guard's saved-register SP.
 * All caller/frame links have already been checked by each entry.
 */
.macro capsule frame, fail
    ldr x16, [sp, #(\frame + 16)]
    cmp x0, x16
    b.ne \fail
    ldr x16, [sp, #(\frame + 24)]
    ldr x17, =COOKIE
    cmp x16, x17
    b.ne \fail
    ldr w16, [sp, #(\frame + 36)]
    cmp w16, #1
    b.ne \fail
    ldr w16, [sp, #(\frame + 40)]
    cmp w16, #4
    b.ne \fail
    ldr w16, [x0]
    cmp w16, #1
    b.ne \fail
    ldr w16, [x0, #8]
    cmp w16, #8
    b.ne \fail
    ldr w16, [x0, #0x388]
    cmp w16, #4
    b.ne \fail
    ldr w16, [x0, #0x38c]
    cmp w16, #4
    b.ne \fail
    ldr w16, [x0, #0x390]
    ldr w17, [sp, #(\frame + 32)]
    cmp w16, w17
    b.ne \fail
    sub w16, w16, #4
    cmp w16, #2
    b.hi \fail
    ldr w16, [x0, #0x3a0]
    cmp w16, #4
    b.ne \fail
.endm
.balign 16
.global og4k_scoped_nrmt_height_hook
og4k_scoped_nrmt_height_hook:
    save_check
    ldr x16, =0x410A541C
    cmp x30, x16
    b.ne 9f
    ldr x16, [sp, #0xe8]           // native main-frame savedx30 at+C8
    adr x17, scope_return
    cmp x16, x17
    b.ne 9f
    capsule 0xf0, 9f
    restore_check
    mov w8, #2756
    b original_410A5910
9:  restore_check
    b legacy_nrmt_hook
.balign 16
.global og4k_scoped_nrmt_crop_hook
og4k_scoped_nrmt_crop_hook:
    save_check
    ldr x16, =0x410A64C0
    cmp x30, x16
    b.ne 9f
    ldr x16, [sp, #0x58]           //6470's savedx30 at+38
    ldr x17, =0x410A6348
    cmp x16, x17
    b.ne 9f
    ldr x16, [sp, #0x60]           //6334's savedLR
    ldr x17, =0x410A541C
    cmp x16, x17
    b.ne 9f
    ldr x16, [sp, #0x138]          // main-frame savedx30 at+C8
    adr x17, scope_return
    cmp x16, x17
    b.ne 9f
    capsule 0x140, 9f
    restore_check
    mov w8, #2752
    b original_410A6D10
9:  restore_check
    b legacy_crop_hook
.ltorg
