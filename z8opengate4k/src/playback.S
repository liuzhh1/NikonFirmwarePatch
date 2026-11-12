/* File-based playback companions. Derived from reviewed D10/UI predicates.
 * No shooting-mode globals in the file classifier or preview projection.
 * Runtime playback tags reuse D10's media-ID ownership and clear/fallback.
 * Recognition of candidate geometry does not qualify decoding that geometry.
 */
.text
.balign 16
.global og4k_aspect_class_hook
og4k_aspect_class_hook:
    ldrh w8, [x0, #0x39a]
    stp x29, x30, [sp, #-32]!
    str x0, [sp, #16]
    bl original_4078E154
    b aspect_common
.balign 16
.global og4k_aspect_class_thumb_hook
og4k_aspect_class_thumb_hook:
    ldrh w8, [x0, #0x39a]
    stp x29, x30, [sp, #-32]!
    str x0, [sp, #16]
    bl original_4078E1E0
aspect_common:
    cmp w0, #1
    b.ne aspect_done
    ldr x0, [sp, #16]
    ldr w0, [x0]                    // composer's own file ID
    bl og4k_playback_file
    cmp w0, #0
    cset w0, eq                     // either OG identity -> class0, else1
aspect_done:
    ldp x29, x30, [sp], #32
    ret

/* w0=file ID -> w0=2 for4K,1 for8K,0 otherwise.
 * Keep x1-x7,x12-x30 (original class leaves only clobber x8-x11).
 * Release every non-null native record, even when lookup reports failure.
 */
.balign 16
.global og4k_playback_file
og4k_playback_file:
    stp x29, x30, [sp, #-176]!
    stp x1, x2, [sp, #16]
    stp x3, x4, [sp, #32]
    stp x5, x6, [sp, #48]
    stp x7, x12, [sp, #64]
    stp x13, x14, [sp, #80]
    stp x15, x16, [sp, #96]
    stp x17, x18, [sp, #112]
    stp x19, x20, [sp, #128]
    stp xzr, xzr, [sp, #144]
    mov w19, wzr
    add x1, sp, #144
    add x2, sp, #152
    bl original_407CD844
    tbz w0, #0, file_release
    ldr x20, [sp, #152]
    cbz x20, file_release
    ldr w8, [x20, #4]
    ubfx w8, w8, #20, #3
    cmp w8, #6                      // N-RAW only; Q3 quality bits unchanged
    b.ne file_release
    ldr w8, [x20, #0xc]             // packed two native u16 active dimensions
    mov w9, #4128
    movk w9, #2752, lsl #16
    cmp w8, w9
    b.ne file_eight_k
    mov w19, #2
    b file_release
file_eight_k:
    mov w9, #8256
    movk w9, #5504, lsl #16
    cmp w8, w9
    cset w19, eq
file_release:
    ldr x0, [sp, #144]
    cbz x0, file_done
    bl original_4085AA7C
file_done:
    mov w0, w19
    ldp x19, x20, [sp, #128]
    ldp x17, x18, [sp, #112]
    ldp x15, x16, [sp, #96]
    ldp x13, x14, [sp, #80]
    ldp x7, x12, [sp, #64]
    ldp x5, x6, [sp, #48]
    ldp x3, x4, [sp, #32]
    ldp x1, x2, [sp, #16]
    ldp x29, x30, [sp], #176
    ret

/* Same bounded destination/source rules as original UI/D4, for4K only.
 * Existing8K/other requests run the original preview chain unchanged.
 */
.balign 16
.global og4k_preview_hook
og4k_preview_hook:
    stp x19, x20, [sp, #-96]!
    stp x21, x30, [sp, #16]
    stp x0, x1, [sp, #32]
    str x2, [sp, #48]
    mov x19, x0
    mov x20, x1
    ldr w8, [x19, #0x50]
    cbnz w8, preview_done
    ldr w8, [x19, #0x34]
    cmp w8, #8
    b.eq preview_thumb
    cmp w8, #2
    b.ne preview_done
    ldr w8, [x19, #0x3c]
    mov w9, #1024
    movk w9, #682, lsl #16
    cmp w8, w9
    b.ne preview_done
    ldrh w8, [x19, #0x30]
    cbnz w8, preview_overview
    ldrh w8, [x19, #0x40]
    cmp w8, #1024
    b.ne preview_done
    mov w8, #3                      // original D4 full page
    b preview_large_source
preview_overview:
    ldr w8, [x19, #0x30]
    mov w9, #65
    movk w9, #47, lsl #16
    cmp w8, w9
    b.ne preview_done
    ldr w8, [x19, #0x40]
    mov w9, #484
    movk w9, #272, lsl #16
    cmp w8, w9
    b.ne preview_done
    mov w8, #2                      // original UI overview box
preview_large_source:
    str w8, [sp, #56]
    mov w9, #1920
    movk w9, #1080, lsl #16
    b preview_source
preview_thumb:
    ldrb w8, [x19, #0x48]
    cmp w8, #1
    b.ne preview_done
    ldrh w8, [x19, #0x4a]
    cmp w8, #8
    b.ne preview_done
    ldrh w8, [x19, #0x40]
    ldrh w9, [x19, #0x42]
    cbz w8, preview_done
    cbz w9, preview_done
    add w8, w8, w8
    add w9, w9, w9, lsl #1
    sub w8, w8, w9
    add w8, w8, #2
    cmp w8, #4
    b.hi preview_done
    mov w8, #1
    str w8, [sp, #56]
    mov w9, #640
    movk w9, #360, lsl #16
preview_source:
    ldr w8, [x20, #0x58]
    cbnz w8, preview_done
    ldr w8, [x20, #0x60]
    cbnz w8, preview_done
    ldr w8, [x20, #0x64]
    cmp w8, w9
    b.ne preview_done
    ldr w8, [x20, #0x68]
    cmp w8, w9
    b.ne preview_done
    ldr w0, [x20]
    bl og4k_playback_file
    cmp w0, #2
    b.ne preview_done
    ldr w8, [sp, #56]
    cmp w8, #1
    b.eq preview_uncrop
    cmp w8, #3
    b.eq preview_full
    mov w8, #103
    movk w8, #47, lsl #16
    str w8, [x19, #0x30]
    mov w8, #408
    movk w8, #272, lsl #16
    str w8, [x19, #0x40]
    b preview_done
preview_full:
    str wzr, [x19, #0x30]
    mov w8, #1024
    movk w8, #682, lsl #16
    str w8, [x19, #0x40]
    b preview_done
preview_uncrop:
    strb wzr, [x19, #0x48]
preview_done:
    ldp x0, x1, [sp, #32]
    ldr x2, [sp, #48]
    ldp x21, x30, [sp, #16]
    ldp x19, x20, [sp], #96
    b legacy_preview_full_page_hook

/* Add4K to D10's file/media-ID-qualified moving playback fit. Native RAW
 * request and proxy association are checked separately. All misses delegate
 * D10, which clears a prior tag on a new non-target main playback request.
 */
.balign 16
.global og4k_playback_capture_hook
og4k_playback_capture_hook:
    stp x8, x9, [sp, #-32]!
    stp x10, x11, [sp, #16]
    ldr x8, =0xA045F08F8
    cmp x19, x8
    b.ne capture_fallback
    ldr w9, [x23, #0x23c]
    cmp w9, #0x31
    b.ne capture_proxy
    ldp w10, w11, [x23]
    mov w9, #4128
    cmp w10, w9
    b.ne capture_coded
    cmp w11, #2752
    b.eq capture_target
capture_coded:
    mov w9, #4140
    cmp w10, w9
    b.ne capture_fallback
    cmp w11, #2756
    b.ne capture_fallback
    b capture_target
capture_proxy:
    cmp w9, #2
    b.ne capture_fallback
    ldr w9, [x23]
    cmp w9, #1920
    b.ne capture_fallback
    ldr w9, [x23, #4]
    cmp w9, #1080
    b.ne capture_fallback
    ldr x10, =0xA0456A820
    ldrh w9, [x10, #0xa0]
    cmp w9, #2
    b.ne capture_fallback
    ldrh w9, [x10, #0xa4]
    cmp w9, #1920
    b.ne capture_fallback
    ldrh w9, [x10, #0xa6]
    cmp w9, #1080
    b.ne capture_fallback
    ldrh w9, [x10, #0xfa]
    cmp w9, #1
    b.ne capture_fallback
    ldrh w9, [x10, #0xfc]
    cmp w9, #0x31
    b.ne capture_fallback
    ldrh w9, [x10, #0x102]
    mov w11, #4128
    cmp w9, w11
    b.ne capture_fallback
    ldrh w9, [x10, #0x104]
    cmp w9, #2752
    b.ne capture_fallback
capture_target:
    ldr w9, [sp, #32]              // native request media ID
    cbz w9, capture_fallback
    orr x9, x9, #0x100000000
    ldr x8, =0xA0FF6F000
    str x9, [x8, #8]
    dmb ishst
    ldp x10, x11, [sp, #16]
    ldp x8, x9, [sp], #32
    ldr w8, [x23, #0x240]
    b original_40711534
capture_fallback:
    ldp x10, x11, [sp, #16]
    ldp x8, x9, [sp], #32
    b legacy_playback_capture_hook
.ltorg
