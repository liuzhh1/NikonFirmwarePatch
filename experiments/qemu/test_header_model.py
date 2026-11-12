#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-2.0-or-later
# Declarations adapted from WonderLantern/z8-qemu's capture-drain contract,
# Copyright (C) 2026 RdWing. The functions under test are actual model C.
import argparse
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

p=argparse.ArgumentParser(add_help=False);p.add_argument('--qemu-repo',type=Path,required=True)
args,rest=p.parse_known_args();sys.argv=[sys.argv[0],*rest]
spec=importlib.util.spec_from_file_location('source_helpers',args.qemu_repo/'tests/source_helpers.py')
helpers=importlib.util.module_from_spec(spec);spec.loader.exec_module(helpers)

DECLARATIONS=r'''
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <string.h>
#define ARRAY_SIZE(x) (sizeof(x)/sizeof((x)[0]))
typedef uint64_t hwaddr;
typedef struct {
 bool z8_still,capture_nv16_model,raw_pipeline_model;
 bool engine1543_video_program_known,video_raw_transport_model,video_raw_ring_latched;
 bool engine1543_video_control_model,engine1543_capture_control_model,video_receiver_before_supplier_model;
 bool og4k_header_model,og4k_header_wait;
 uint32_t og4k_header_rejected;uint64_t og4k_header_starts,og4k_header_releases;
 bool capture_nv16_requested,video_raw_frame_ready,engine1530_active;
 uint32_t engine152c_stream_pending,engine1530_config[0x100/4];
 uint64_t capture_stream_rearms,engine1543_retained_starts;
 bool engine1543_held[3],engine1543_active[3];
 uint32_t engine1542_config[40][0x1000/4],engine1543_latched[3][0x1000/4];
 uint32_t engine1543_valid[3],engine1542_pending[40];
 uint64_t engine1543_buffer_valid[3],engine1543_starts[3],engine1543_stops[3],engine1543_holds[3];
 struct {uint32_t config[0x2000/4];} engine1518[3];
 unsigned raw_pipeline_row,raw_pipeline_bank;bool raw_pipeline_wait_bank,raw_pipeline_refill_notified;
} NikonZ8State;
typedef struct {int cpu_index;struct {uint64_t pc;} env;} CPU;
static CPU *current_cpu;
#define ARM_CPU(x) (x)
static uint32_t engine1542_bases[40];
static unsigned invalid,irqs,photo_requests,photo_tries;static bool packet_owner;
static bool video_raw_packet_blocks_producer(NikonZ8State*s){(void)s;return packet_owner;}
static bool engine1543_retained_video_start(NikonZ8State*s,unsigned j,uint64_t v){(void)s;(void)j;(void)v;return false;}
static bool capture_stream_can_rearm(NikonZ8State*s,unsigned j){(void)s;(void)j;return false;}
static bool capture_nv16_prepare(NikonZ8State*s){(void)s;photo_requests++;return false;}
static void capture_nv16_try(NikonZ8State*s){(void)s;photo_tries++;}
static void capture_nv16_cancel(NikonZ8State*s){s->capture_nv16_requested=false;}
static void raw_pipeline_irq_update(NikonZ8State*s){(void)s;irqs++;}
static void unknown_access(NikonZ8State*s,hwaddr a,uint64_t v,unsigned n,bool w){(void)s;(void)a;(void)v;(void)n;(void)w;invalid++;}
'''

CHECKS=r'''
static NikonZ8State fresh(void){
 NikonZ8State s={0};s.og4k_header_model=s.engine1543_video_control_model=s.engine1543_capture_control_model=true;
 s.capture_nv16_model=true;s.engine1543_valid[1]=15;s.engine1543_buffer_valid[1]=UINT64_C(0x000f000f000f000f);
 uint32_t*c=s.engine1542_config[11],*a=s.engine1542_config[1];c[1]=0x103;c[2]=0x302;c[4]=0x29;
 a[3]=0x01000000;a[4]=1;a[0x38/4]=a[0x3c/4]=640;
 for(unsigned r=0;r<4;r++)for(unsigned v=0;v<2;v++)c[(0x200+r*0x80+v*8)/4]=0xe0000000u+(r%2?0x43800:0)+(v?0xb80:0);
 return s;
}
static void supplier(NikonZ8State*s){
 uint32_t*a=s->engine1542_config[1],*src=s->engine1518[0].config;
 a[1]=0x202;a[2]=0x0f010000;a[3]=0x71200410;a[0x38/4]=a[0x3c/4]=5888;a[0x4c/4]=1920;a[0x50/4]=1080;
 src[0xbc/4]=src[0xc0/4]=1;src[0xb0/4]=src[0xb4/4]=5760;
}
int main(void){
 NikonZ8State s=fresh();s.og4k_header_model=false;engine1543_control_write(&s,11,0x15432004,0x101);
 assert(invalid==1&&photo_requests==1&&!s.engine1543_active[1]);invalid=photo_requests=0;
 for(unsigned test=0;test<13;test++){
  s=fresh();packet_owner=false;unsigned bit=0;
  switch(test){
   case 0:s.engine1543_buffer_valid[1]^=1;bit=4;break;
   case 1:s.engine1542_config[11][0x288/4]++;bit=128;break;
   case 2:s.engine1542_config[11][0x284/4]=1;bit=128;break;
   case 3:s.engine1543_active[1]=true;bit=2;break;
   case 4:s.engine1543_held[1]=true;bit=2;break;
   case 5:s.capture_nv16_requested=true;bit=16;break;
   case 6:s.engine1542_pending[11]=1;bit=8;break;
   case 7:s.engine1542_pending[1]=1;bit=8;break;
   case 8:s.engine1518[0].config[0xb0/4]=1;bit=64;break;
   case 9:s.video_raw_frame_ready=true;bit=16;break;
   case 10:packet_owner=true;bit=16;break;
   case 11:s.engine1542_config[1][0x38/4]++;bit=32;break;
   case 12:s.engine152c_stream_pending=4;bit=16;break;
  }
  assert(og4k_header_rejections(&s,1,0x101)==bit&&!og4k_header_start(&s,1,0x101));
 }
 packet_owner=false;s=fresh();assert(!og4k_header_start(&s,0,0x101)&&!og4k_header_start(&s,1,0x201));
 engine1543_control_write(&s,11,0x15432004,0x101);
 assert(s.engine1543_active[1]&&s.og4k_header_wait&&s.og4k_header_starts==1);
 assert(!invalid&&!photo_requests&&!photo_tries&&!irqs&&!s.engine1542_pending[11]);
 assert(!og4k_header_poll(&s)&&!s.og4k_header_releases&&!s.engine1543_video_program_known);
 supplier(&s);s.engine1542_pending[1]=1;assert(!og4k_header_poll(&s));s.engine1542_pending[1]=0;
 s.engine1543_held[1]=true;assert(!og4k_header_poll(&s));s.engine1543_held[1]=false;
 assert(og4k_header_poll(&s)&&s.og4k_header_releases==1&&s.engine1543_video_program_known);
 assert(og4k_header_poll(&s)&&s.og4k_header_releases==1&&!irqs);
 s=fresh();engine1543_control_write(&s,11,0x15432004,0x101);supplier(&s);
 for(unsigned r=0;r<4;r++)for(unsigned v=0;v<2;v++)s.engine1542_config[11][(0x200+r*0x80+v*8)/4]=0xe0000000u+(r%2?0xe100:0)+(v?0xb80:0);
 assert(engine1543_video_ready(&s,1)&&!og4k_header_poll(&s));
 engine1543_control_write(&s,11,0x15432004,0x100);
 assert(!s.engine1543_active[1]&&!s.og4k_header_wait&&og4k_header_poll(&s));
 assert(!irqs&&!photo_requests&&!photo_tries&&!invalid);
 puts("Default-off, 13 rejection classes, latch, readiness, idempotence, changed program and cancel passed");
 return 0;
}
'''

class HeaderModelContract(unittest.TestCase):
    def test_production_c(self):
        source=(args.qemu_repo/'qemu/nikon-z8-lab.c').read_text()
        header=(args.qemu_repo/'qemu/nikon-z8-og4k-header.h').read_text()
        body=DECLARATIONS
        for name in ('engine1543_capture_ready','engine1543_video_ready','engine1543_ready'):body+=helpers.function(source,name)
        for name in ('og4k_header_rejections','og4k_header_start','og4k_header_poll'):body+=helpers.function(header,name)
        body+=helpers.function(source,'engine1543_control_write')+CHECKS
        with tempfile.TemporaryDirectory(prefix='z8-header-contract-') as folder:
            path=Path(folder);(path/'test.c').write_text(body)
            subprocess.run(['cc','-std=c11','-Wall','-Wextra','-Werror',str(path/'test.c'),'-o',str(path/'test')],check=True)
            result=subprocess.run([str(path/'test')],check=True,capture_output=True,text=True);print(result.stdout.strip())

if __name__=='__main__':unittest.main()
