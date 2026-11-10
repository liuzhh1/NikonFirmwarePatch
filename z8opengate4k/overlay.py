"""Emulator-only MAIN overlay. Does not emit a Nikon flashable package.

Preserves all six main-menu OG choices (8.3K and 4.1K) plus the 80 factory
rows. i-menu integration, cancellation, recorder metadata/budgets and codec
acceptance are not qualified; this prototype must not be used on a camera.
"""
import hashlib,json,struct
from pathlib import Path
from verify import verify_pair,decode
from z8prores.package import require_official_input
from z8patch.image import branch
from .compiled import compile_frontend,BASE as CODE_BASE

B=0x40160000
MENU,ROWS,EVENTS=0x408C0000,0x408C2000,0x408C3000
TEXT,TABLES=0x40A50000,0x40A70000

def make_main(original,candidate,compiler):
    require_official_input(original)
    verification=verify_pair(original,candidate,
        ['framing','video-quality','log-colour','photo-tools'],expected_version='03.11',expected_tag='p0')
    stock=decode(original)[581844:82389553]
    baseline=decode(candidate)[581844:82389553]
    new=bytearray(baseline);writes=[]
    code,compiled=compile_frontend(compiler)
    profile=json.loads((Path(__file__).parent/'frontend-profile.json').read_text())
    if (compiled['sha256'],compiled['source_sha256'])!=(profile['sha256'],profile['source_sha256']):
        raise ValueError('Frontend code/source differ from the staged lab profile')
    def put(address,data,why):
        off=address-B
        if off<0 or off+len(data)>len(new):raise ValueError('Overlay write outside MAIN')
        writes.append(dict(address=hex(address),bytes=len(data),purpose=why))
        new[off:off+len(data)]=data
    # Rebuild added language strings with three appended IDs, retaining every
    # existing ID and all original native offset entries.
    text=bytearray();tables=bytearray()
    for language in range(36):
        table=struct.unpack_from('<Q',baseline,0x311C5A0+8*language)[0]-B
        blob=struct.unpack_from('<Q',baseline,0x387AF58+8*language)[0]-B
        old=struct.unpack_from('<3226i',baseline,table)
        translations=[baseline[blob+old[i]:blob+old[i+1]].decode('utf-16le') for i in range(3137,3225)]
        labels=[f'4128x2752 {rate}p [FX 3:2] LAB' for rate in (30,25,24)]
        offsets=list(old[:3137])
        for value in translations+labels:
            offsets.append(TEXT+len(text)-B-blob);text.extend(value.encode('utf-16le'))
        offsets.append(TEXT+len(text)-B-blob)
        if len(offsets)!=3229:raise ValueError('Lab string-table shape differs')
        put(B+0x311C5A0+8*language,struct.pack('<Q',TABLES+len(tables)),'lab language directory')
        tables.extend(struct.pack('<3229i',*offsets))
    if TEXT+len(text)>TABLES or TABLES+len(tables)>0x40AF0000:raise ValueError('Lab language allocation overflow')
    put(TEXT,text,'existing translations and three explicitly labeled lab rows')
    put(TABLES,tables,'36 extended language tables; original IDs retained')
    menu=bytearray(baseline[MENU-B:MENU-B+3*24])
    rows=bytearray(baseline[ROWS-B:ROWS-B+3*44])
    events=bytearray(baseline[EVENTS-B:EVENTS-B+3*8])
    for j,rate in enumerate((4,5,6)):
        item=0x35C3+j
        menu.extend(struct.pack('<6I',item,6,rate,4,1,0x80000003+j))
        row=list(struct.unpack_from('<11I',stock,61501836+(60+j)*44))
        row[0]=3225+j;row[6]=item;rows.extend(struct.pack('<11I',*row))
        events.extend(stock[61505360+(60+j)*8:61505360+(61+j)*8])
    menu.extend(stock[43776736:43776736+80*24])
    rows.extend(stock[61501836:61501836+80*44])
    events.extend(stock[61505360:61505360+80*8])
    if (len(menu),len(rows),len(events))!=(86*24,86*44,86*8):raise ValueError('Main-menu shape differs')
    put(MENU,menu,'six OG main-menu identities plus 80 preserved factory rows')
    put(ROWS,rows,'three 4K LAB rows after three preserved 8.3K OG rows')
    put(EVENTS,events,'native per-rate event bindings')
    put(B+79480592+32,struct.pack('<H',86),'frame-size page row count')
    for address,value,mask in [(0x4056C73C,16+86*24,0x003FFC00),
                               (0x40570334,86,0x001FFFE0),
                               (0x40572E44,85,0x001FFFE0)]:
        # Exact instruction-family checks are performed by the reviewed baseline;
        # only its immediate field changes here, in the emulator-only image.
        word=struct.unpack_from('<I',new,address-B)[0]
        shift=10 if mask==0x003FFC00 else 5
        put(address,struct.pack('<I',(word&~mask)|(value<<shift)),'86-row native bound')
    if any(baseline[CODE_BASE-B:CODE_BASE-B+len(code)]):raise ValueError('Lab code cave is not empty')
    put(CODE_BASE,code,'isolated frontend prototype')
    for address,name in [(0x40F7938C,'og4k_configuration_hook'),(0x41062070,'og4k_half_plan_hook'),
                         (0x410665F4,'og4k_geometry_hook'),(0x41066A70,'og4k_inner_hook'),
                         (0x40572EA0,'og4k_menu_summary_match_hook'),(0x411717F4,'og4k_driver_entry_hook')]:
        put(address,branch(address,compiled['entries'][name],False),name)
        if address==0x41062070:put(address+4,bytes.fromhex('1f2003d5'),'second replaced frontend instruction')
    output=bytes(new)
    return output,dict(schema='z8-opengate4k-emulator-main-1',verification=verification,
        main_sha256=hashlib.sha256(output).hexdigest(),base_main_sha256=hashlib.sha256(baseline).hexdigest(),
        compiled=compiled,writes=writes,main_menu_rows=86,
        firmware_generated=False,flash_package_generated=False,recording_4k_open_gate_implemented=False,
        scope='Emulator-only selection/frontend prototype; no i-menu, cancel, recorder metadata or TICO acceptance')
