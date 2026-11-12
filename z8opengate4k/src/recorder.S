/* Experimental recorder companions;2756 coded rows are not TICO-qualified.
 * No flash package. Preserve D10 and all non-target routes.
 */
#define OG_STATE 0xA0FF6F000
#define OG_FLAG 0xA03D5C02B
.text
.balign 16
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
.macro selected fail
    ldr x16, =OG_FLAG
    ldrb w16, [x16]
    cmp w16, #1
    b.ne \fail
    ldr x16, =OG_STATE
    ldr w16, [x16]
    cmp w16, #1
    b.ne \fail
    ldr x16, =0xA03D5C014
    ldr w16, [x16]
    cmp w16, #6
    b.ne \fail
    ldr x16, =0xA03BB71D8
    ldr w17, [x16]
    cmp w17, #4
    b.ne \fail
    ldr w17, [x16, #4]
    sub w17, w17, #4
    cmp w17, #2
    b.hi \fail
    ldr x16, =0xA02A979FE
    ldrh w16, [x16]
    cmp w16, #2756
    b.ne \fail
.endm
.macro snapshot fail
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
    ldr x16, =0xA03BB71DC
    ldr w17, [x16]
    ldr w16, [x0, #0x390]
    cmp w16, w17
    b.ne \fail
    ldr w16, [x0, #0x3a0]
    cmp w16, #4
    b.ne \fail
.endm
.macro file_mode fail
    ldr w16, [x0, #0xc]
    cmp w16, #4
    b.ne \fail
    ldr x16, =0xA03BB71DC
    ldr w17, [x16]
    ldr w16, [x0, #0x10]
    cmp w16, w17
    b.ne \fail
.endm

/* One shared descriptor/budget join. It must work before frontend install;
 * use the original RAW table/index, not a later GUI or geometry cache.
 */
.global og4k_record_table_hook
og4k_record_table_hook:
    save_check
    ldr x16, =OG_FLAG
    ldrb w16, [x16]
    cmp w16, #1
    b.ne 9f
    ldr x16, =0xA03D5C014
    ldr w16, [x16]
    cmp w16, #6
    b.ne 9f
    mov w17, wzr
    sub x16, x9, #9
    cmp x16, #2
    b.ls 1f
    mov w17, #1
    sub x16, x9, #30
    cmp x16, #2
    b.hi 9f
1:  ldr x16, =0x42AB3C90
    cmp x10, x16
    b.eq 2f
    ldr x16, =0x408C1000
    cmp x10, x16
    b.eq 2f
    ldr x16, =0x40953000
    cmp x10, x16
    b.eq 3f
    ldr x16, =0x40957000
    cmp x10, x16
    b.eq 3f
    ldr x16, =0x409533F0
    cmp x10, x16
    b.eq 4f
    ldr x16, =0x409573F0
    cmp x10, x16
    b.ne 9f
4:  cbz w17, 9f
    ldr x10, =OG4K_BASIC
    b 5f
3:  cbnz w17, 9f
    ldr x10, =OG4K_FINE
    b 5f
2:  ldr x10, =OG4K_COMMON
5:  restore_check
    madd x8, x9, x8, x10
    b original_40D1E654
9:  restore_check
    b legacy_tier_table_hook
.balign 16
.global og4k_nrmt_hook
og4k_nrmt_hook:
    save_check
    selected 9f
    snapshot 9f
    restore_check
    mov w8, #2756
    b original_410A5910
9:  restore_check
    b legacy_nrmt_hook
.balign 16
.global og4k_crop_hook
og4k_crop_hook:
    save_check
    selected 9f
    snapshot 9f
    restore_check
    mov w8, #2752
    b original_410A6D10
9:  restore_check
    b legacy_crop_hook
/* Native4K entry, separate from the existing8K branch. */
.balign 16
.global og4k_nctg_height_hook
og4k_nctg_height_hook:
    mov w8, #2322
    save_check
    selected 9f
    file_mode 9f
    ldrb w16, [x0, #0xe0]
    cbnz w16, 9f
    mov w8, #2752
9:  restore_check
    b original_406D2C90
.balign 16
.global og4k_proxy_main_height_hook
og4k_proxy_main_height_hook:
    mov w9, #2322
    save_check
    selected 9f
    file_mode 9f
    mov w9, #2752
9:  restore_check
    b original_406D313C
.balign 16
.global og4k_nctg_crop_hook
og4k_nctg_crop_hook:
    save_check
    selected 9f
    file_mode 9f
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
.ltorg
