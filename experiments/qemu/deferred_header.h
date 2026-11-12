/* SPDX-License-Identifier: GPL-2.0-or-later
 * Experimental fresh N-RAW receiver control latch. Not a chip specification.
 * Included after the upstream ready/retained helpers. Default OFF.
 */
static uint32_t og4k_header_rejections(NikonZ8State *s, unsigned j, uint64_t value)
{
    if (!s->og4k_header_model || !s->engine1543_video_control_model ||
        !s->engine1543_capture_control_model || j != 1 || value != 0x101) { return 1; }
    uint32_t mask = 0;
    const uint32_t *c = s->engine1542_config[11], *a = s->engine1542_config[1];
    if (s->engine1543_active[1] || s->engine1543_held[1]) { mask |= 2; }
    if (s->engine1543_valid[1] != 15 ||
        s->engine1543_buffer_valid[1] != UINT64_C(0x000f000f000f000f) ||
        (c[1] & ~3u) != 0x100 || c[2] != 0x302 || c[3] || c[4] != 0x29) { mask |= 4; }
    if (s->engine1542_pending[11] || s->engine1542_pending[1]) { mask |= 8; }
    if (s->capture_nv16_requested || video_raw_packet_blocks_producer(s) ||
        s->video_raw_frame_ready || s->engine152c_stream_pending || s->engine1530_active ||
        (s->engine1530_config[0x1c/4] & 12)) { mask |= 16; }
    if (a[1] || a[2] || a[3] != 0x01000000 || a[4] != 1 ||
        a[0x38/4] != 640 || a[0x3c/4] != 640 || a[0x4c/4] || a[0x50/4]) { mask |= 32; }
    for (unsigned i = 0; i < ARRAY_SIZE(s->engine1518[0].config); i++) {
        if (s->engine1518[0].config[i]) { mask |= 64; break; }
    }
    for (unsigned row = 0; row < 4; row++) {
        for (unsigned plane = 0; plane < 2; plane++) {
            unsigned off = 0x200 + row * 0x80 + plane * 8;
            uint32_t expected = 0xe0000000u + (row % 2 ? 0x43800 : 0) + (plane ? 0xb80 : 0);
            if (c[off/4] != expected || c[(off+4)/4]) { mask |= 128; }
        }
    }
    return mask;
}

static bool og4k_header_start(NikonZ8State *s, unsigned j, uint64_t value)
{
    uint32_t rejected = og4k_header_rejections(s, j, value);
    if (s->og4k_header_model && j == 1 && value == 0x101) {
        s->og4k_header_rejected = rejected;
        fprintf(stderr, "Z8_OG4K_HEADER reject=%u capture=%d pending_header=%u pending_supplier=%u packet=%d frame=%d receiver=%u decoder=%d decoder_pending=%u\n",
            rejected, s->capture_nv16_requested, s->engine1542_pending[11], s->engine1542_pending[1],
            video_raw_packet_blocks_producer(s), s->video_raw_frame_ready, s->engine152c_stream_pending,
            s->engine1530_active, s->engine1530_config[0x1c/4]);
    }
    return rejected == 0;
}

static bool og4k_header_poll(NikonZ8State *s)
{
    if (!s->og4k_header_wait) { return true; }
    if (!s->engine1543_active[1] || s->engine1543_held[1] || !engine1543_video_ready(s, 1)) { return false; }
    const uint32_t *c = s->engine1542_config[11], *prior = s->engine1543_latched[1];
    if (c[2] != prior[2] || c[3] != prior[3] || c[4] != prior[4]) { return false; }
    for (unsigned row = 0; row < 4; row++) {
        for (unsigned word = 0; word < 4; word++) {
            unsigned index = (0x200 + row * 0x80) / 4 + word;
            if (c[index] != prior[index]) { return false; }
        }
    }
    s->og4k_header_wait = false;
    s->og4k_header_releases++;
    s->engine1543_video_program_known = true;
    return true;
}

static bool get_og4k_header_model(Object *obj, Error **errp)
{ return NIKON_Z8_LAB(obj)->og4k_header_model; }
static void set_og4k_header_model(Object *obj, bool value, Error **errp)
{
    NikonZ8State *s = NIKON_Z8_LAB(obj);
    if (s->image_ram.ram || s->image_ram.rom_device) {
        error_setg(errp, "early N-RAW header model immutable after realization"); return;
    }
    s->og4k_header_model = value;
}
