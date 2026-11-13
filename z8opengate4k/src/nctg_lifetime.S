/* Pin4K NCTG identity at the native recording task's private ImgInfo copy.
 * 4071E208 copies100h of attributes;4071E220 copies4490h of ImgInfo;
 * 4071E228 publishes the private ImgInfo pointer into attributes+0.
 * This is a single native working record, not a general writer registry.
 * No native attribute/ImgInfo spare fields are used. NRMT is unchanged.
 */
#define ATTR 0xA0460BE88
#define PRIVATE_INFO 0xA0460EC20
#define STAMP 0xA0FF6F200
#define MAGIC 0x4B47344F
.text
.balign 16
.global og4k_nctg_clone_hook
og4k_nctg_clone_hook:
    stp x19, x30, [sp, #-48]!
    stp x20, x21, [sp, #16]
    stp x22, x23, [sp, #32]
    mov x19, x0
    mov x20, x1
    mov x21, x2
    ldr x8, =STAMP
    str xzr, [x8]                 // invalidate before replacing native contents
    dmb ishst
    bl original_4127A900           // exact original copy, return value preserved
    mov x22, x0
    ldr x8, =PRIVATE_INFO
    cmp x19, x8
    b.ne clone_done
    mov x8, #0x4490
    cmp x21, x8
    b.ne clone_done
    cbz x20, clone_done
    ldr x8, =ATTR
    ldr x9, [x8]
    cmp x9, x20                   // earlier native attribute copy owns this source
    b.ne clone_done
    mov w23, wzr
    ldr w9, [x8, #0x20]
    cmp w9, #6                    // file-owned N-RAW type
    b.ne clone_publish
    ldr w9, [x8, #0xc]
    cmp w9, #4
    b.ne clone_publish
    ldr w9, [x8, #0x10]
    sub w10, w9, #4
    cmp w10, #2
    b.hi clone_publish
    ldr x9, =0xA03D5C02B
    ldrb w9, [x9]
    cmp w9, #1
    b.ne clone_publish
    ldr x9, =0xA03D5C014
    ldr w9, [x9]
    cmp w9, #6
    b.ne clone_publish
    ldr x9, =0xA03BB71D8
    ldr w10, [x9]
    cmp w10, #4
    b.ne clone_publish
    ldr w9, [x9, #4]
    ldr w10, [x8, #0x10]
    cmp w9, w10                    // reject a differently selected current mode
    b.ne clone_publish
    ldr x9, =0xA0FF6F000
    ldr w9, [x9]
    cmp w9, #1
    b.ne clone_publish
    ldr x9, =0xA02A979FE
    ldrh w9, [x9]
    cmp w9, #2756
    b.ne clone_publish
    mov w23, #1
clone_publish:
    ldr x9, =STAMP
    str x19, [x9, #8]
    ldr w10, [x8, #0x10]
    str w10, [x9, #16]
    str w23, [x9, #20]
    ldr w10, =MAGIC
    str w10, [x9, #24]
    dmb ishst
    str x8, [x9]                  // owner key last; ordinary copies publish target0
clone_done:
    mov x0, x22
    ldp x22, x23, [sp, #32]
    ldp x20, x21, [sp, #16]
    ldp x19, x30, [sp], #48
    ret

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
/* Only the native private record is owned. No current selection reads here.
 * Revalidate owner pointer and copied attributes before overriding any field.
 * The4490h source is opaque; do not assume it has NRMT's snapshot layout.
 */
.macro owned fail
    ldr x16, =STAMP
    ldr x17, [x16]
    cmp x0, x17
    b.ne \fail
    dmb ishld                      // pair with owner-last publication
    ldr x17, =ATTR
    cmp x0, x17
    b.ne \fail
    ldr w17, [x16, #24]
    ldr w16, =MAGIC
    cmp w16, w17
    b.ne \fail
    ldr x16, =STAMP
    ldr w17, [x16, #20]
    cmp w17, #1
    b.ne \fail
    ldr x17, [x16, #8]
    ldr x16, [x0]
    cmp x16, x17
    b.ne \fail
    ldr x17, =PRIVATE_INFO
    cmp x16, x17
    b.ne \fail
    ldr w17, [x0, #0x20]
    cmp w17, #6
    b.ne \fail
    ldr w17, [x0, #0xc]
    cmp w17, #4
    b.ne \fail
    ldr w17, [x0, #0x10]
    sub w17, w17, #4
    cmp w17, #2
    b.hi \fail
    ldr x16, =STAMP
    ldr w16, [x16, #16]
    ldr w17, [x0, #0x10]
    cmp w16, w17
    b.ne \fail
.endm
.balign 16
.global og4k_owned_height_hook
og4k_owned_height_hook:
    mov w8, #2322
    save_check
    owned 9f
    ldrb w16, [x0, #0xe0]
    cbnz w16, 9f
    mov w8, #2752
9:  restore_check
    b original_406D2C90
.balign 16
.global og4k_owned_proxy_main_hook
og4k_owned_proxy_main_hook:
    mov w9, #2322
    save_check
    owned 9f
    mov w9, #2752
9:  restore_check
    b original_406D313C
.balign 16
.global og4k_owned_crop_hook
og4k_owned_crop_hook:
    save_check
    owned 9f
    ldrb w16, [x0, #0xe0]
    cbnz w16, 9f
    restore_check
    mov w8, #11
    strh w8, [x1, #0x332]
    mov w8, #4140
    strh w8, [x1, #0x334]
    strh w8, [x1, #0x338]
    mov w8, #2756
    strh w8, [x1, #0x336]
    strh w8, [x1, #0x33a]
    strh wzr, [x1, #0x33c]
    strh wzr, [x1, #0x33e]
    mov w0, #1
    ret
9:  restore_check
    b legacy_nctg_crop_hook
.balign 16
.global og4k_nctg_reset_hook
og4k_nctg_reset_hook:
    cmp w19, #1
    b.ne 9f
    stp x8, x9, [sp, #-16]!
    ldr x8, =STAMP
    stp xzr, xzr, [x8]
    stp xzr, xzr, [x8, #16]
    stp xzr, xzr, [x8, #32]
    stp xzr, xzr, [x8, #48]
    dsb ishst
    ldp x8, x9, [sp], #16
9:  b legacy_boot_reset_d8_hook
.ltorg
