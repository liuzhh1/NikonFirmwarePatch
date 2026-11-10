"""Execute the real AArch64 prototype with the reviewed D10 fallback in Unicorn.

Opt in with OG4K_COMPILER=/path/to/clang and install unicorn. No Nikon firmware
is needed or included. Fixture data comes from the original 4.1K runtime trace.
"""
import importlib.util,json,os,struct,unittest
from pathlib import Path
from z8opengate4k.compiled import compile_frontend,BASE
from z8patch.compiled import compile_unit

AVAILABLE=bool(os.environ.get('OG4K_COMPILER')) and importlib.util.find_spec('unicorn') is not None
if AVAILABLE:
    from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE
    import unicorn.arm64_const as A

@unittest.skipUnless(AVAILABLE,'Set OG4K_COMPILER and install unicorn for AArch64 execution')
class FrontendExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        compiler=os.environ['OG4K_COMPILER']
        cls.code,cls.meta=compile_frontend(compiler)
        cls.legacy,legacy=compile_unit('opengate',compiler)
        published=json.loads((Path(__file__).resolve().parents[1]/'resources/compiled.json').read_text())['units']['opengate']
        if legacy['sha256']!=published['sha256'] or legacy['symbols']!=published['symbols']:
            raise AssertionError('D10 fallback differs from its reviewed bytes or symbols')

    def setUp(self):
        self.uc=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
        self.uc.mem_map(0x40160000,0x02000000)
        self.uc.mem_map(0xA00000000,0x10000000)
        self.uc.mem_write(0x40960000,self.legacy);self.uc.mem_write(BASE,self.code)
        self.snapshot=0xA06000000;self.plan=0xA06001000;self.geometry=0xA06002000
        for i in range(31):self.uc.reg_write(getattr(A,f'UC_ARM64_REG_X{i}'),0x123000+i)
        self.uc.reg_write(A.UC_ARM64_REG_SP,0xA06100000)
        self.uc.reg_write(A.UC_ARM64_REG_X30,0x40160000)
        self.uc.reg_write(A.UC_ARM64_REG_NZCV,0xA0000000)
        self.set_mode()
        self.w32(0xA0FF6F01C,0x12345678) # D7 owns this cancel-session word.
        self.stops={0x40160000,0x40F79390,0x41062078,0x410665F8,0x41066A74,0x40572EF0,0x411717F8}
        self.uc.hook_add(UC_HOOK_CODE,lambda u,a,n,x:u.emu_stop() if a in self.stops else None)

    def w32(self,a,v):self.uc.mem_write(a,struct.pack('<I',v))
    def h(self,a):return struct.unpack('<H',self.uc.mem_read(a,2))[0]
    def word(self,a):return struct.unpack('<I',self.uc.mem_read(a,4))[0]
    def set_mode(self,rate=4,size=4,kind=1,nominal=4,request=4,flag=1,file_type=6):
        self.uc.mem_write(self.snapshot,bytes(0x3A4))
        for offset,value in [(0,kind),(0x388,nominal),(0x38c,size),(0x390,rate),(0x3a0,request)]:self.w32(self.snapshot+offset,value)
        self.uc.mem_write(0xA03D5C02B,bytes([flag]));self.w32(0xA03D5C014,file_type)
        self.w32(0xA03BB71D8,size);self.w32(0xA03BB71DC,rate)
    def call(self,name):
        self.uc.emu_start(self.meta['entries'][name],0x40160000,count=3000)
        self.assertIn(self.uc.reg_read(A.UC_ARM64_REG_PC),self.stops,'Execution did not reach a bounded continuation')
    def configure(self):
        self.uc.reg_write(A.UC_ARM64_REG_X0,1);self.uc.reg_write(A.UC_ARM64_REG_X19,self.snapshot)
        self.call('og4k_configuration_hook')
    def seed_geometry(self):
        raw=bytearray(0x70)
        for off,value in [(0,1920),(2,1080),(0xc,4128),(0xe,2322),(0x10,1920),(0x12,1080),
                          (0x14,6),(0x16,10),(0x24,1920),(0x26,1080),(0x28,1920),(0x2a,1080),
                          (0x48,4140),(0x4a,2344),(0x4c,4140),(0x4e,2344),(0x64,4140),(0x66,2344)]:
            struct.pack_into('<H',raw,off,value)
        self.uc.mem_write(self.geometry,bytes(raw));self.uc.reg_write(A.UC_ARM64_REG_X19,self.geometry)
        return bytes(raw)

    def test_low_rate_predicate_and_snapshot_preservation(self):
        for rate in (4,5,6):
            self.set_mode(rate=rate);before=bytes(self.uc.mem_read(self.snapshot,0x3a4))
            self.uc.reg_write(A.UC_ARM64_REG_X0,self.snapshot);self.call('og4k_wanted_hook')
            self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_X0),1)
            self.assertEqual(bytes(self.uc.mem_read(self.snapshot,0x3a4)),before)
    def test_predicate_exclusions(self):
        for fields in [dict(rate=3),dict(rate=7),dict(size=6),dict(kind=0),dict(nominal=5),
                       dict(request=1),dict(flag=0),dict(flag=2),dict(file_type=2)]:
            self.set_mode(**fields);self.uc.reg_write(A.UC_ARM64_REG_X0,self.snapshot)
            self.call('og4k_wanted_hook');self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_X0),0,fields)
    def test_configuration_and_register_preservation(self):
        regs=[getattr(A,f'UC_ARM64_REG_X{i}') for i in (8,9,10,11,30)]
        before=[self.uc.reg_read(r) for r in regs];sp=self.uc.reg_read(A.UC_ARM64_REG_SP)
        self.w32(0xA0FF6F004,2);self.configure()
        self.assertEqual([self.h(a) for a in (0xA02A979D2,0xA02A979FE,0xA02A97D12,0xA02A97D16)],[2756]*4)
        self.assertEqual(self.h(0xA02A97A2A),2752)
        self.assertEqual((self.word(0xA0FF6F000),self.word(0xA0FF6F004),self.word(0xA0FF6F010)),(1,0,2))
        self.assertEqual(self.word(0xA0FF6F01C),0x12345678)
        self.assertEqual([self.uc.reg_read(r) for r in regs],before);self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_SP),sp)
    def test_native_fallback_restores_ordinary_geometry(self):
        self.configure();self.set_mode(flag=0);self.configure()
        self.assertEqual((self.h(0xA02A979EE),self.h(0xA02A979FE),self.h(0xA02A97A2A)),(4688,2344,2322))
        self.assertEqual(self.word(0xA0FF6F000),0)
    def test_eight_k_open_gate_fallback_stays_available(self):
        self.set_mode(size=6);self.configure()
        self.assertEqual((self.h(0xA02A979EE),self.h(0xA02A979FE)),(5520,2756))
        self.assertEqual(self.word(0xA0FF6F000),1)
    def test_plan_eleven_and_ten_both_work(self):
        self.configure()
        for kind in (11,10):
            self.uc.mem_write(self.plan,struct.pack('<4I',kind,4,4,6));self.uc.reg_write(A.UC_ARM64_REG_X20,self.plan)
            self.call('og4k_half_plan_hook')
            self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_X9),2756)
            self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_X1)&65535,0x74A0)
    def test_geometry_changes_only_declared_fields(self):
        self.configure();before=self.seed_geometry()
        regs=[getattr(A,f'UC_ARM64_REG_X{i}') for i in (8,9,10,11)]
        values=[self.uc.reg_read(r) for r in regs];flags=self.uc.reg_read(A.UC_ARM64_REG_NZCV)
        self.call('og4k_geometry_hook');after=bytes(self.uc.mem_read(self.geometry,0x70))
        expected=bytearray(before)
        for off,value in [(0xe,2752),(0x16,2),(0x4a,2756),(0x4e,2756),(0x5e,2),(0x66,2760),(0x68,values[2]&65535)]:struct.pack_into('<H',expected,off,value)
        self.assertEqual(after,bytes(expected));self.assertEqual([self.uc.reg_read(r) for r in regs],values)
        self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_NZCV),flags)
    def test_geometry_excludes_ordinary_and_high_rate(self):
        for fields in [dict(flag=0),dict(size=6),dict(rate=3),dict(file_type=2)]:
            self.set_mode(**fields);self.w32(0xA0FF6F000,1);before=self.seed_geometry()
            self.uc.reg_write(A.UC_ARM64_REG_X10,0);self.call('og4k_geometry_hook')
            self.assertEqual(bytes(self.uc.mem_read(self.geometry,0x68)),before[:0x68],fields)
    def test_driver_entry_covers_native_variants_two_and_three(self):
        self.configure()
        for variant in (2,3):
            self.uc.mem_write(self.plan,struct.pack('<4I',5,8,0,variant))
            self.uc.reg_write(A.UC_ARM64_REG_X0,self.plan)
            self.call('og4k_driver_entry_hook')
            self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_X0),14)
    def test_driver_entry_delegates_other_modes(self):
        self.configure()
        for kind,readout,variant in ((5,4,2),(8,8,2),(5,8,1),(5,8,4)):
            self.uc.mem_write(self.plan,struct.pack('<4I',kind,readout,0,variant))
            self.uc.reg_write(A.UC_ARM64_REG_X0,self.plan)
            self.call('og4k_driver_entry_hook')
            self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_PC),0x411717F8)
            self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_X0),self.plan)
            self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_X8),self.plan)

    def test_new_and_existing_summary_resources(self):
        record=0xA06003000;icons=0xA06004000
        for i in range(19):self.uc.mem_write(icons+i*12,struct.pack('<3I',i,1000+i,2000+i))
        for first,index in [(0x35C3,9),(0x35C0,2)]:
            for rate in range(3):
                for quality,base in [(1,1000),(0,2000)]:
                    self.w32(record,first+rate);self.w32(record+0x10,1)
                    self.uc.reg_write(A.UC_ARM64_REG_X20,record+0xc)
                    self.uc.reg_write(A.UC_ARM64_REG_X24,icons)
                    self.uc.reg_write(A.UC_ARM64_REG_X26,6)
                    self.uc.reg_write(A.UC_ARM64_REG_X23,quality)
                    self.call('og4k_menu_summary_match_hook')
                    self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_X1),base+index+rate)

    def test_coded_candidate_is_bounded_and_preserves_flags(self):
        self.configure();self.w32(self.plan+0x20,4);self.uc.reg_write(A.UC_ARM64_REG_X0,self.plan)
        self.uc.reg_write(A.UC_ARM64_REG_X8,4140);flags=self.uc.reg_read(A.UC_ARM64_REG_NZCV)
        self.call('og4k_inner_hook');self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_X9),2756)
        self.assertLessEqual(2756,self.h(0xA02A979FE));self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_NZCV),flags)
    def test_coded_candidate_rejects_stale_state(self):
        self.w32(0xA0FF6F000,1);self.set_mode(flag=0);self.w32(self.plan+0x20,4)
        self.uc.reg_write(A.UC_ARM64_REG_X0,self.plan);self.uc.reg_write(A.UC_ARM64_REG_X8,4140)
        self.call('og4k_inner_hook');self.assertEqual(self.uc.reg_read(A.UC_ARM64_REG_X9),2330)

if __name__=='__main__':unittest.main()
