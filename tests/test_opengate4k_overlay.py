"""Optional real-input integration checks. Firmware remains user supplied and untracked."""
import os,json,struct,unittest
from pathlib import Path
from verify import decode
from z8opengate4k.overlay import make_main

READY=all(os.environ.get(n) for n in ('OG4K_COMPILER','OG4K_ORIGINAL','OG4K_BASELINE'))
@unittest.skipUnless(READY,'Set OG4K_COMPILER/OG4K_ORIGINAL/OG4K_BASELINE for real-input integration')
class OverlayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        old=Path(os.environ['OG4K_ORIGINAL']).read_bytes();base=Path(os.environ['OG4K_BASELINE']).read_bytes()
        cls.stock=decode(old)[581844:82389553];cls.base=decode(base)[581844:82389553]
        cls.new,cls.report=make_main(old,base,os.environ['OG4K_COMPILER'])
    def test_preserves_eight_k_and_all_factory_main_rows(self):
        a=0x408c0000-0x40160000
        rows=list(struct.iter_unpack('<6I',self.new[a:a+86*24]))
        self.assertEqual(len({r[0] for r in rows}),86)
        self.assertEqual([r[3] for r in rows[:6]],[6,6,6,4,4,4])
        self.assertEqual([r[2] for r in rows[:6]],[4,5,6,4,5,6])
        self.assertEqual([r[4] for r in rows[:6]],[1]*6)
        self.assertEqual(self.new[a:a+72],self.base[a:a+72])
        self.assertEqual(self.new[a+144:a+86*24],self.stock[43776736:43776736+80*24])
    def test_native_language_offsets_and_existing_translations_preserved(self):
        for language in range(36):
            def strings(image,count):
                table=struct.unpack_from('<Q',image,0x311c5a0+8*language)[0]-0x40160000
                blob=struct.unpack_from('<Q',image,0x387af58+8*language)[0]-0x40160000
                offsets=struct.unpack_from(f'<{count}i',image,table)
                return offsets,[image[blob+offsets[i]:blob+offsets[i+1]] for i in range(3137,count-1)]
            a,x=strings(self.base,3226);b,y=strings(self.new,3229)
            self.assertEqual(a[:3137],b[:3137]);self.assertEqual(x,y[:88])
            for text,rate in zip(y[88:],(30,25,24)):
                self.assertEqual(text.decode('utf-16le'),f'4128x2752 {rate}p [FX 3:2] LAB')
    def test_retains_reviewed_injected_code_and_production_flags(self):
        a=0x40960000-0x40160000
        self.assertEqual(self.new[a:a+11568],self.base[a:a+11568])
        self.assertEqual(self.new[0xEB29FC:0xEB2A08],self.base[0xEB29FC:0xEB2A08])
        self.assertFalse(self.report['flash_package_generated'])
        self.assertFalse(self.report['recording_4k_open_gate_implemented'])
        self.assertEqual(len(self.new),81807709)
    def test_changes_remain_inside_declared_overlay_windows(self):
        windows=sorted((int(w['address'],16)-0x40160000,int(w['address'],16)-0x40160000+w['bytes'])
                       for w in self.report['writes'])
        end=0
        for start,stop in windows:
            self.assertGreaterEqual(start,end)
            self.assertEqual(self.base[end:start],self.new[end:start]);end=stop
        self.assertEqual(self.base[end:],self.new[end:])

if __name__=='__main__':unittest.main()
