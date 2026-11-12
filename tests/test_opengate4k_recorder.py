"""Actual AArch64 recorder companions and complete-input byte preservation."""
import json
import os
from pathlib import Path
import struct
import unittest
from z8opengate4k.recorder import BASE, TABLES, OLD_TABLES, RECORD, project_tables, compile_recorder
import test_opengate4k_frontend as frontend


def fixture():
    rows=[(8268,5512,30000,1001,1,3000000000)]*42
    for i,n,d,hi,no in ((9,30000,1001,898,468),(10,25000,1000,758,398),(11,24000,1001,728,378)):
        rows[i]=(4140,2330,n,d,1,hi*1000000)
        rows[i+21]=(4140,2330,n,d,1,no*1000000)
    return {name:b''.join(RECORD.pack(*r) for r in rows) for name in TABLES}


class BudgetProjection(unittest.TestCase):
    def test_twelve_records_only_and_fractional_fps_preserved(self):
        old=fixture();new,edits=project_tables(old)
        self.assertEqual(len(edits),12)
        changed={'common':{9,10,11,30,31,32},'fine':{9,10,11},'basic':{30,31,32}}
        for table in TABLES:
            for i in range(42):
                before,after=(RECORD.unpack_from(t[table],i*24) for t in (old,new))
                if i not in changed[table]:self.assertEqual(before,after)
                else:
                    self.assertEqual(after[:2],(4140,2756));self.assertEqual(before[2:5],after[2:5])
                    self.assertEqual(after[5]%1000000,0)
        self.assertEqual([RECORD.unpack_from(new['common'],i*24)[3] for i in (9,10,11)],[1001,1000,1001])

    def test_fixed_budget_vectors_and_quality_order(self):
        _,edits=project_tables(fixture())
        self.assertEqual([e['candidate_bps']//1000000 for e in edits],
                         [1061,548,719,377,893,465,607,322,855,445,582,308])
        for n in (30000,25000,24000):
            b={e['tier']:e['candidate_bps'] for e in edits if e['numerator']==n}
            self.assertTrue(b['high']>b['fine']>b['normal']>b['basic'])

    def test_inconsistent_identity_and_truncated_tables_rejected(self):
        for table,offset,value in [('common',9*24+8,0),('fine',9*24+2,2332),
                                   ('basic',30*24+4,60000),('common',30*24+12,0)]:
            tables={k:bytearray(v) for k,v in fixture().items()}
            struct.pack_into('<H' if offset%24==2 else '<I',tables[table],offset,value)
            with self.assertRaises(ValueError):project_tables(tables)
        tables=fixture();tables['common']=tables['common'][:-1]
        with self.assertRaises(ValueError):project_tables(tables)


@unittest.skipUnless(frontend.AVAILABLE,'Set OG4K_COMPILER and install Unicorn')
class RecorderExecution(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        frontend.FrontendExecution.setUpClass()
        cls.code,cls.meta=compile_recorder(os.environ['OG4K_COMPILER'])
        root=Path(__file__).resolve().parents[1]
        profile=json.loads((root/'z8opengate4k/recorder-profile.json').read_text())
        if cls.meta!=profile['compiled']:raise AssertionError('Recorder profile differs')
        cls.legacy_entries={k:int(v['va'],16) for k,v in json.loads((root/'resources/compiled.json').read_text())['units']['opengate']['symbols'].items()}
        cls.tables,_=project_tables(fixture())

    def setUp(self):
        self.f=frontend.FrontendExecution();self.f.setUp();self.u=self.f.uc;self.A=frontend.A
        self.u.mem_map(0x42160000,0x03000000);self.u.mem_write(BASE,self.code)
        self.ctx,self.out=self.f.snapshot,0xA06004000
        self.u.mem_write(self.out,b'\xa5'*0x400)
        self.f.stops.update({0x40D1E654,0x410A5910,0x410A6D10,0x406D2C90,0x406D313C,0x406D3828,0x406D2C3C})
        for n,a in OLD_TABLES.items():self.u.mem_write(a,fixture()[n]);self.u.mem_write(TABLES[n],self.tables[n])
        for a in (0x42AB3C90,0x40953000,0x409533F0):self.u.mem_write(a,fixture()['common'])
        self.f.w32(0xA02A979EE,5520)
        for a,v in ((0x440D0908,2330),(0x440D0910,4652),(0x440D0AF0,2322),(0x440D0AF8,4644)):self.f.w32(a,v)
        self.setr(0,self.ctx);self.setr(1,self.out);self.mode()

    def r(self,i):return self.u.reg_read(getattr(self.A,f'UC_ARM64_REG_X{i}'))
    def setr(self,i,v):self.u.reg_write(getattr(self.A,f'UC_ARM64_REG_X{i}'),v)
    def mode(self,flag=1,size=4,rate=4,state=1,file_type=6,height=2756,actual=8):
        self.f.set_mode(flag=flag,size=size,rate=rate,file_type=file_type)
        for a,v in ((0xA0FF6F000,state),(0xA02A979FE,height),(self.ctx+8,actual),(self.ctx+0xc,size),(self.ctx+0x10,rate)):self.f.w32(a,v)
    def call(self,name,legacy=False):
        entries=self.legacy_entries if legacy else self.meta['entries']
        self.u.emu_start(entries[name],0x40160000,count=4000)
        self.assertIn(self.u.reg_read(self.A.UC_ARM64_REG_PC),self.f.stops)
    def table(self,base,index):
        self.setr(8,24);self.setr(9,index);self.setr(10,base);self.call('og4k_record_table_hook');return self.r(8)

    def test_all_rates_and_four_tiers_share_descriptor_and_budget(self):
        for rate,i in ((4,9),(5,10),(6,11)):
            self.mode(rate=rate)
            for old,table,index in ((0x42AB3C90,'common',i),(0x408C1000,'common',i+21),
                                     (0x40953000,'fine',i),(0x409533F0,'basic',i+21)):
                a=self.table(old,index);self.assertEqual(a,TABLES[table]+index*24)
                self.assertEqual(RECORD.unpack(bytes(self.u.mem_read(a,24)))[:2],(4140,2756))

    def test_unrelated_record_and_mode_fall_back(self):
        for fields in (dict(flag=0),dict(flag=2),dict(file_type=2)):
            self.mode(**fields);self.assertEqual(self.table(0x42AB3C90,9),0x42AB3C90+9*24)
        self.mode()
        for base,index in ((0x42AB3C90,8),(0x42AB3C90,12),(0x40953000,30),(0x409533F0,9),(0x42AB3A50,9)):
            self.assertFalse(BASE<=self.table(base,index)<0x4096C000)

    def test_budget_lookup_precedes_frontend_installation(self):
        self.mode(state=0,size=6,rate=3,height=2344)
        self.assertEqual(self.table(0x42AB3C90,9),TABLES['common']+9*24)
        self.assertEqual(self.table(0x40953000,10),TABLES['fine']+10*24)

    def test_table_join_preserves_stack_flags_and_scratch(self):
        before=[self.r(i) for i in (0,1,11,12,16,17,30)]
        sp=self.u.reg_read(self.A.UC_ARM64_REG_SP);flags=self.u.reg_read(self.A.UC_ARM64_REG_NZCV)
        self.table(0x42AB3C90,9)
        self.assertEqual(before,[self.r(i) for i in (0,1,11,12,16,17,30)])
        self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_SP),sp);self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_NZCV),flags)

    def test_snapshot_metadata_matches_coded_and_active_height(self):
        for rate in (4,5,6):
            self.mode(rate=rate);self.setr(8,0x440D0900);self.setr(9,2)
            self.call('og4k_nrmt_hook');self.assertEqual(self.r(8),2756)
            self.setr(10,0x440D0AE0);self.setr(8,4);self.call('og4k_crop_hook');self.assertEqual(self.r(8),2752)

    def test_stale_snapshot_and_wrong_readout_use_native_height(self):
        for fields in (dict(flag=0),dict(rate=3),dict(actual=4),dict(file_type=2)):
            self.mode(**fields);self.setr(8,0x440D0900);self.setr(9,2)
            self.call('og4k_nrmt_hook');self.assertEqual(self.r(8),2330)
            self.setr(10,0x440D0AE0);self.setr(8,4);self.call('og4k_crop_hook');self.assertEqual(self.r(8),2322)
        self.mode();self.f.w32(self.ctx+0x390,5);self.setr(8,0x440D0900);self.setr(9,2)
        self.call('og4k_nrmt_hook');self.assertEqual(self.r(8),2330)

    def test_raw_and_proxy_associated_main_height(self):
        self.call('og4k_nctg_height_hook');self.assertEqual(self.r(8),2752)
        self.call('og4k_proxy_main_height_hook');self.assertEqual(self.r(9),2752)
        self.u.mem_write(self.ctx+0xe0,b'\x01')
        self.call('og4k_nctg_height_hook');self.assertEqual(self.r(8),2322)
        self.call('og4k_proxy_main_height_hook');self.assertEqual(self.r(9),2752)

    def test_crop_writes_only_its_declared_record(self):
        before=bytes(self.u.mem_read(self.out,0x400));self.call('og4k_nctg_crop_hook')
        expected=bytearray(before);struct.pack_into('<7H',expected,0x332,11,4140,2756,4140,2756,0,0)
        self.assertEqual(bytes(self.u.mem_read(self.out,0x400)),bytes(expected));self.assertEqual(self.r(0),1)
        self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_SP),0xA06100000)

    def test_proxy_crop_delegates_without_writing(self):
        self.u.mem_write(self.ctx+0xe0,b'\x01');before=bytes(self.u.mem_read(self.out,0x400))
        self.call('og4k_nctg_crop_hook');self.assertEqual(bytes(self.u.mem_read(self.out,0x400)),before)
        self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_PC),0x406D3828)
        self.assertEqual(self.u.reg_read(self.A.UC_ARM64_REG_SP),0xA06100000-64)

    def test_existing_eight_k_metadata_and_quality_are_preserved(self):
        self.mode(size=6,actual=4);self.setr(8,0x440D0900);self.setr(9,4)
        self.call('og4k_nrmt_hook');self.assertEqual(self.r(8),5512)
        self.setr(10,0x440D0AE0);self.setr(8,6);self.call('og4k_crop_hook');self.assertEqual(self.r(8),5504)
        self.call('nctg_height_hook',legacy=True);self.assertEqual(self.r(8),5504)
        self.assertEqual(self.table(0x40953000,2),0x40957000+2*24)
        self.setr(0,self.ctx);self.setr(1,self.out);self.call('og4k_nctg_crop_hook')
        self.assertEqual(struct.unpack('<7H',self.u.mem_read(self.out+0x332,14)),(11,8280,5520,8280,5520,0,0))


REAL_INPUTS=all(os.environ.get(n) for n in ('OG4K_COMPILER','OG4K_ORIGINAL','OG4K_BASELINE'))
@unittest.skipUnless(REAL_INPUTS,'Set original/baseline for complete-input integration')
class RecorderOverlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from verify import decode
        from z8opengate4k.overlay import make_main
        from z8opengate4k.recorder import make_recorder_main
        original=Path(os.environ['OG4K_ORIGINAL']).read_bytes();baseline=Path(os.environ['OG4K_BASELINE']).read_bytes()
        cls.baseline=decode(baseline)[581844:82389553]
        cls.frontend,_=make_main(original,baseline,os.environ['OG4K_COMPILER'])
        cls.new,cls.report=make_recorder_main(original,baseline,os.environ['OG4K_COMPILER'])

    def test_complete_build_is_still_main_only_and_unqualified(self):
        self.assertEqual(len(self.new),81807709)
        for key in ('flash_package_generated','recording_4k_open_gate_implemented'):self.assertFalse(self.report[key])
        for key in ('tico_qualified','file_callback_lifetime_qualified'):self.assertFalse(self.report['recorder'][key])
        self.assertEqual(self.report['frontend_main_sha256'],'e293e2d97e55be35b6399014afb13eebbf6666d3d532cbef83960d98b586a959')

    def test_old_code_and_eight_k_and_native_proxy_branches_remain(self):
        b=0x40160000
        for a,n in ((0x40960000,11568),(0x406D2C9C,4),(0x406D3150,4),(0x406D2C24,0x24),(0x408C0000,86*24)):
            self.assertEqual(self.new[a-b:a-b+n],self.frontend[a-b:a-b+n])
        for a in OLD_TABLES.values():self.assertEqual(self.new[a-b:a-b+1008],self.baseline[a-b:a-b+1008])

    def test_all_writes_are_declared_and_nonoverlapping(self):
        b=0x40160000;end=0
        for start,stop in sorted((int(w['address'],16)-b,int(w['address'],16)-b+w['bytes']) for w in self.report['writes']):
            self.assertGreaterEqual(start,end);self.assertEqual(self.new[end:start],self.baseline[end:start]);end=stop
        self.assertEqual(self.new[end:],self.baseline[end:])

    def test_real_tables_preserve_all_non_target_records(self):
        b=0x40160000;changed={'common':{9,10,11,30,31,32},'fine':{9,10,11},'basic':{30,31,32}}
        for name,target in TABLES.items():
            old=self.baseline[OLD_TABLES[name]-b:OLD_TABLES[name]-b+1008];new=self.new[target-b:target-b+1008]
            for i in range(42):
                if i not in changed[name]:self.assertEqual(new[i*24:(i+1)*24],old[i*24:(i+1)*24])
                else:self.assertEqual(RECORD.unpack_from(new,i*24)[1],2756)


if __name__=='__main__':unittest.main()
