#!/usr/bin/env python3
"""Observe stock or pinned lab MAIN setup without runtime guest RAM patches.

Use the existing QEMU CLI options after --qemu-repo. --replay is an append-only
control JSON during the run; creating its sibling .done file stops cleanly.
The lab environment variables select a diagnostic payload only and never waive
production package validation. A hardware-model frontier is a failed run.
The opt-in selector15 fixture changes one explicitly declared external-ROM byte;
it is synthetic input, not recovered factory calibration or a camera patch.
"""
from pathlib import Path
import argparse,sys,json,re,struct,importlib.util,os,hashlib
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from z8opengate4k.diagnostics import first_uart_exception
parser=argparse.ArgumentParser(description='Read-only 4.1K mode/frontier observation with append-only external controls',add_help=False,allow_abbrev=False)
parser.add_argument('--qemu-repo',type=Path,required=True)
parser.add_argument('--transport-helper',type=Path)
parser.add_argument('--experimental-movie-selector15',action='store_true',help='Declared synthetic external-ROM selector15=1; not recovered camera data')
options,remaining=parser.parse_known_args()
lab=options.qemu_repo.resolve()
if not (lab/'tools/run.py').is_file():parser.error('Existing z8-qemu checkout required')
sys.argv=[sys.argv[0],*remaining]
sys.path.insert(0,str(lab/'tools'))
adapter=None
if options.transport_helper:
 spec=importlib.util.spec_from_file_location('z8_tcp',options.transport_helper.resolve())
 adapter=importlib.util.module_from_spec(spec);spec.loader.exec_module(adapter)
import run,stream,replay,movie_inputs
if options.experimental_movie_selector15:
 original_attach=movie_inputs.attach
 def attach_selector15(g,args):
  if not (movie_inputs.native_modes_enabled(args) and args.experimental_movie_selector10):
   raise ValueError('selector15 requires the complete Movie profile including selector10')
  original_attach(g,args)
  data=b'\x01';path=g.out/'experimental-selector15.bin';path.write_bytes(data)
  g.command+=['-device',f'loader,file={path},addr=0x47f5af4f,force-raw=on']
  g.data['experimental_movie_selector15']=dict(address='0x47f5af4f',value=1,sha256=hashlib.sha256(data).hexdigest(),
    factory_calibration=False,basis='Explicit A/B input for native selector index15; parameter record remains synthetic')
 movie_inputs.attach=attach_selector15
active={};BasePeer=stream.Peer;BaseReplay=replay.Replay
ROM_POINTS={0x41170d5c:'rom-selector',0x41170d70:'rom-byte',0x41170d84:'rom-record'}
VIDEO_POINTS={0x41062018:'plan',0x410622c8:'frontend',0x410665f8:'geometry',0x41066a9c:'coded',**ROM_POINTS}
POINTS={0x40f7a090:'snapshot',0x411717f4:'driver',**VIDEO_POINTS}
def vr(g,cpu,a,n):
 if not any(lo<=a and a+n<=hi for lo,hi in [(0xa00000000,0xa40000000),(0xe20000000,0xe40000000)]):return None
 g.rsp(f'Hg{cpu+1:x}');r=g.rsp(f'm{a:x},{n:x}',expect_ok=False)
 return bytes.fromhex(r) if len(r)==n*2 and re.fullmatch('[0-9a-fA-F]+',r) else None
class Peer(BasePeer):
 def __init__(self,g,**kw):
  super().__init__(g,**kw);self.obs={};self.epoch=0;active.update(peer=self,g=g);self.arm_obs()
 def arm_obs(self,points=None):
  self.epoch+=1
  for a,n in (POINTS if points is None else points).items():
   if a not in self.obs:self.g.rsp(f'Z1,{a:x},4');self.obs[a]=(n,self.epoch)
 def handle(self):
  g=self.g;orig=g.qmp.hmp;observed=[]
  def read(command,cpu=0):
   text=orig(command,cpu)
   if command!='info registers':return text
   regs={k:int(v,16) for k,v in re.findall(r'\b(X\d\d|PC|SP)=([0-9a-fA-F]+)',text)};pc=regs['PC']
   if pc not in self.obs:return text
   name,ep=self.obs.pop(pc);g.rsp(f'z1,{pc:x},4');row=dict(name=name,epoch=ep,cpu=cpu,pc=hex(pc),inputs=len(g.data.get('interactive_inputs',[])))
   a,n=(regs['X19'],0x3a4) if name=='snapshot' else (regs['X19'],0x212) if name=='frontend' else (regs['X19'],0x70) if name=='geometry' else (regs['X00'],0x40)
   if name in ('snapshot','driver','plan','frontend','geometry','coded'):
    raw=vr(g,cpu,a,n);row['pointer']=hex(a)
    if raw is not None:
     row['data_hex']=raw.hex()
     if name=='snapshot':row['fields']={k:struct.unpack_from('<I',raw,v)[0] for k,v in dict(kind=0,actual=8,nominal=0x388,size=0x38c,rate=0x390,request=0x3a0).items()}
     if name in ('driver','plan'):row['words']=list(struct.unpack('<16I',raw))
     if name=='frontend':row['dimensions']=[struct.unpack_from('<H',raw,x)[0] for x in (6,2,0x1a2,0x19e)]
     if name=='geometry':row['u16']={hex(x):struct.unpack_from('<H',raw,x)[0] for x in (0xc,0xe,0x10,0x12,0x48,0x4a,0x5c,0x5e,0x64,0x66)}
    if name=='coded':row['coded']=[regs['X08']&65535,regs['X09']&65535]
    if name=='driver':
     ret=regs['X30']
     if 0x40160000<=ret<0x42560000 and ret not in self.obs:self.obs[ret]=('driver-return',ep);g.rsp(f'Z1,{ret:x},4')
   if name=='driver-return':row['driver']=regs['X00']
   if name=='snapshot' and row.get('fields',{}).get('kind')==1:
    self.arm_obs(VIDEO_POINTS)
   if name=='driver-return':self.arm_obs(ROM_POINTS)
   if name=='rom-selector':
    address=regs['X14']+regs['X10'];value=vr(g,cpu,address,1)
    row.update(index=regs['X08'],rom_base=hex(regs['X13']),selector_address=hex(address),
               selector_byte=value[0] if value is not None else None)
   if name=='rom-byte':
    selector=regs['X14']&0xffffffff
    row.update(index=regs['X08'],selector_byte=selector,rom_base=hex(regs['X13']),
               predicted_record_base=hex(regs['X13']+(((selector-1)&0xffffffff)<<5)))
   if name=='rom-record':
    address=regs['X13']+regs['X15'];value=vr(g,cpu,address,2)
    row.update(index=regs['X08'],record_base=hex(regs['X13']),record_address=hex(address),
               first_parameter=struct.unpack('<H',value)[0] if value is not None else None)
   g.data.setdefault('og_trace',[]).append(row);observed.append(row)
   return text
  g.qmp.hmp=read
  try:r=super().handle()
  finally:g.qmp.hmp=orig
  return r or bool(observed)
 def close(self):
  for a in self.obs:self.g.rsp(f'z1,{a:x},4')
  self.obs.clear();super().close()
class Replay(BaseReplay):
 def __init__(self,path):super().__init__(path);self.path=path;self.menu_since=None
 def next_input(self):
  actions=BaseReplay(self.path).actions
  if actions[:self.index]!=self.actions[:self.index]:raise ValueError('Consumed controls changed')
  self.actions=actions;active['g'].data['input_replay']=actions;r=super().next_input()
  if r:
   p=active['peer'];p.g.qmp.command('stop');p.handle();p.arm_obs();p.g.qmp.command('cont')
  return r
 def publish(self,frame,row,ready):
  vt=row['virtual_seconds']
  if ready:
   if self.menu_since is None:self.menu_since=vt
  else:self.menu_since=None
  ready=ready and self.menu_since is not None and vt-self.menu_since>=3
  super().publish(frame,row,ready)
  g=active['g'];self.info=row
  (g.out/'observations.json').write_text(json.dumps(g.data.get('og_trace',[]),indent=2))
  (g.out/f'input-{self.sent:03d}.ppm').write_bytes(frame.read_bytes())
  if self.path.with_suffix('.done').exists():self.stop.set()
 def status(self):return dict(super().status(),now=self.now,menu_since=self.menu_since)
stream.Peer=Peer;replay.Replay=Replay
if adapter:run.Guest=adapter.TCPGuest
if os.environ.get('OG4K_LAB_MAIN'):
 import hashlib,os
 stock=Path(os.environ['OG4K_STOCK_MAIN']).resolve();candidate=Path(os.environ['OG4K_LAB_MAIN']).resolve()
 expected=os.environ['OG4K_LAB_SHA256']
 if candidate.stat().st_size!=81807709 or hashlib.sha256(candidate.read_bytes()).hexdigest()!=expected:
  raise ValueError('Explicit lab MAIN identity mismatch')
 BaseGuest=run.Guest
 class LabGuest(BaseGuest):
  def __init__(self,firmware,binary,raw,out):
   super().__init__(stock,binary,raw,out)
   self.firmware=candidate;self.command[self.command.index('-kernel')+1]=str(candidate)
   self.data.update(firmware_sha256=expected,firmware_image_is_modified=True,
    classification='emulator_only_opengate4k_frontend_prototype',recording_tested=False)
 def verify_lab(path):
  if path.resolve()!=stock:raise ValueError('Stock reference path changed')
  return candidate,json.loads((lab/'source-manifest.json').read_text())
 run.Guest=LabGuest;run.verify=verify_lab
try:
 run.main()
finally:
 g=active.get('g')
 if g and (g.out/'result.json').is_file():
  report=json.loads((g.out/'result.json').read_text());uart=g.out/'uart-tx.log'
  if uart.is_file():report['primary_exception']=first_uart_exception(uart.read_text(errors='replace'))
  report['og_trace']=g.data.get('og_trace',[])
  (g.out/'observations.json').write_text(json.dumps(report['og_trace'],indent=2)+'\n')
  (g.out/'result.json').write_text(json.dumps(report,indent=2)+'\n')
