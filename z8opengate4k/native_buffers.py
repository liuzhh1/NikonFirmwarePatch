"""Bounded execution of reviewed native buffer descriptors, without hardware.

This probes descriptor demand and the existing configuration hook. It does not
run the allocator, sensor, DMA or TICO, and cannot qualify a camera package.
"""
from hashlib import sha256
from pathlib import Path
import struct

MAIN_BASE = 0x40160000
MAIN_BYTES = 81807709
MAIN_SHA256 = 'f80ee74d066a38ef8f61e3b29a1349090f9607ba614ce24744724891da4f94a3'
DATA_OFFSET = 0x4B13000
DATA_RAM = 0xA02808000
STATE = 0xA0FF6F000
SNAPSHOT = 0xA06090000
OUTPUT = 0xA060A0000
STACK = 0xA06100000
RETURN = MAIN_BASE
GEOMETRY = 0xA02A979C0
GEOMETRY_BYTES = 0x360

NATIVE_WINDOWS = (
    ('format classification', 0x4105B098, 0x4105B240),
    ('raw stream descriptor', 0x4105C814, 0x4105CA08),
    ('coded stream descriptor', 0x4105CA08, 0x4105CC1C),
    ('outer raster query', 0x41066978, 0x41066A10),
    ('inner raster query before overlay', 0x41066A10, 0x41066A70),
    ('inner raster query after overlay', 0x41066A74, 0x41066AA8),
    ('record-to-file request veneer', 0x40723778, 0x4072377C),
    ('record-to-file request copy', 0x407218E4, 0x40721928),
    ('record payload assembly', 0x40F85618, 0x40F856B8),
    ('record task request read', 0x4071E678, 0x4071E6CC),
)


def raw_layout(data):
    if len(data) != 24: raise ValueError('Native RAW descriptor must have 24 bytes')
    fmt, flags, stride, width, height, inner_w, inner_h, crop_x, crop_y, reserved = struct.unpack('<II8H', data)
    if fmt != 5 or flags or not width or not height: raise ValueError('Unsupported native RAW descriptor')
    if stride != ((width*7//4+31) & ~31): raise ValueError('Unexpected native 14-bit row stride')
    if not 0 < inner_w <= width or not 0 < inner_h <= height:
        raise ValueError('Inner raster exceeds physical buffer descriptor')
    if crop_x+inner_w > width or crop_y+inner_h > height:
        raise ValueError('Cropped raster exceeds physical buffer descriptor')
    return dict(format=fmt, stride_bytes=stride, outer=[width, height],
                coded=[inner_w, inner_h], crop=[crop_x, crop_y],
                minimum_raster_bytes=stride*height, descriptor_hex=data.hex())


class NativeBufferProbe:
    def __init__(self, image):
        if len(image) != MAIN_BYTES or sha256(image).hexdigest() != MAIN_SHA256:
            raise ValueError('Buffer probe requires the reviewed complete experimental MAIN')
        from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
        import unicorn.arm64_const as A
        self.A = A; self.image = image; self.stop_pc = None
        self.u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        self.u.mem_map(MAIN_BASE, 0x05000000)
        self.u.mem_map(0xA00000000, 0x10000000)
        self.u.mem_write(MAIN_BASE, image)
        self.u.mem_write(DATA_RAM, image[DATA_OFFSET:])
        self.hook = self.u.hook_add(UC_HOOK_CODE, self.observe)
        for i in range(31): self.reg(i, 0x123000+i)
        self.u.reg_write(A.UC_ARM64_REG_SP, STACK)
        self.u.reg_write(A.UC_ARM64_REG_NZCV, 0xA0000000)
        self.select()

    def close(self): self.u.hook_del(self.hook)
    def reg(self, i, value=None):
        register = getattr(self.A, f'UC_ARM64_REG_X{i}')
        if value is None: return self.u.reg_read(register)
        self.u.reg_write(register, value)
    def word(self, address, value): self.u.mem_write(address, struct.pack('<I', value))

    def observe(self, u, address, size, data):
        if address in (RETURN, self.stop_pc): u.emu_stop(); return
        if (0x4105B098 <= address < 0x4105B240 or
                0x4105C814 <= address < 0x4105CC1C or
                0x41066978 <= address < 0x41066AA8 or
                0x40960000 <= address < 0x40963000 or
                0x40965000 <= address < 0x40965500 or address == 0x40F7938C): return
        raise AssertionError(f'Unreviewed buffer-probe call {address:#x}, LR={self.reg(30):#x}')

    def select(self, flag=1, rate=4, size=4, file_type=6, actual=8):
        self.u.mem_write(SNAPSHOT, bytes(0x1000))
        for offset, value in ((0, 1), (8, actual), (0x388, 4), (0x38C, size), (0x390, rate), (0x3A0, 4)):
            self.word(SNAPSHOT+offset, value)
        self.u.mem_write(0xA03D5C02B, bytes([flag]))
        for address, value in ((0xA03D5C014, file_type), (0xA03BB71D8, size), (0xA03BB71DC, rate)):
            self.word(address, value)

    def call(self, entry, *args):
        self.u.reg_write(self.A.UC_ARM64_REG_SP, STACK)
        for i, value in enumerate(args): self.reg(i, value)
        self.reg(30, RETURN)
        saved = [self.reg(i) for i in range(19, 30)]
        self.u.emu_start(entry, 0, count=100000)
        if self.u.reg_read(self.A.UC_ARM64_REG_PC) != RETURN:
            raise AssertionError('Native descriptor did not return')
        if saved != [self.reg(i) for i in range(19, 30)] or self.u.reg_read(self.A.UC_ARM64_REG_SP) != STACK:
            raise AssertionError('Native descriptor damaged callee frame')
        return self.reg(0)

    def configure(self, valid=True):
        # This insertion point continues within a larger native frame. Stop at
        # that continuation, then restore CPU context; retain its RAM effects.
        context = self.u.context_save(); self.stop_pc = 0x40F79390
        self.u.reg_write(self.A.UC_ARM64_REG_SP, STACK)
        self.reg(0, int(valid)); self.reg(19, SNAPSHOT); self.reg(30, RETURN)
        try:
            self.u.emu_start(0x40F7938C, 0, count=100000)
            if self.u.reg_read(self.A.UC_ARM64_REG_PC) != self.stop_pc:
                raise AssertionError('Configuration did not reach native continuation')
        finally:
            self.u.context_restore(context); self.stop_pc = None

    def describe(self):
        before = bytes(self.u.mem_read(SNAPSHOT, 0x1000))
        self.u.mem_write(OUTPUT, bytes(0x40))
        if self.call(0x4105C814, SNAPSHOT, OUTPUT) != 1:
            raise AssertionError('Native RAW descriptor rejected fixture')
        raw = raw_layout(bytes(self.u.mem_read(OUTPUT, 24)))
        self.u.mem_write(OUTPUT, bytes(0x40))
        if self.call(0x4105CA08, SNAPSHOT, OUTPUT) != 1:
            raise AssertionError('Native coded descriptor rejected fixture')
        coded = bytes(self.u.mem_read(OUTPUT, 32))
        if before != bytes(self.u.mem_read(SNAPSHOT, 0x1000)):
            raise AssertionError('Descriptor query changed source snapshot')
        return dict(raw=raw, coded_descriptor_hex=coded.hex(),
                    coded=list(struct.unpack_from('<HH', coded, 8)))

    def run(self):
        self.select(); self.word(STATE, 0)
        offset = DATA_OFFSET+GEOMETRY-DATA_RAM
        self.u.mem_write(GEOMETRY, self.image[offset:offset+GEOMETRY_BYTES])
        before = self.describe()
        self.configure(); candidate = self.describe()
        self.select(flag=0); self.configure(); restored = self.describe()
        return dict(schema='z8-opengate4k-native-buffer-audit-1',
                    main_sha256=MAIN_SHA256, before_configuration=before,
                    after_configuration=candidate, after_disable=restored,
                    extra_raw_raster_bytes=candidate['raw']['minimum_raster_bytes']-before['raw']['minimum_raster_bytes'],
                    ordinary_descriptor_restored=before == restored,
                    snapshot_actual_readout=8, rates_exercised=[4],
                    actual_pool_capacity_verified=False, native_allocation_order_verified=False,
                    physical_dma_or_tico_executed=False, real_record_entry_executed=False,
                    camera_package_generated=False,
                    record_entry_static_path=['0x40f856b4 -> 0x40723778',
                                              '0x40723778 -> 0x407218e4',
                                              '0x407218e4 copies 0x48 bytes to 0xa046130b8',
                                              '0x4071e6bc reads request-kind pointer at message +0x38'],
                    scope='Native descriptor demand and configuration/disable effects only; pool capacity, allocation order, real session and hardware are unqualified',
                    native_windows=[dict(name=name, address=hex(start), bytes=end-start,
                                         sha256=sha256(self.image[start-MAIN_BASE:end-MAIN_BASE]).hexdigest())
                                    for name, start, end in NATIVE_WINDOWS])


def audit_main(path):
    path = Path(path)
    if path.stat().st_size != MAIN_BYTES: raise ValueError('Wrong experimental MAIN length')
    probe = NativeBufferProbe(path.read_bytes())
    try: return probe.run()
    finally: probe.close()
