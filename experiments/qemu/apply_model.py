#!/usr/bin/env python3
"""Apply the isolated default-off header experiment to an exact Z8 model tree."""
import argparse
import hashlib
from pathlib import Path
import subprocess

BASE='d50b07dbaeebae45b2cff936e5bfcd85251ac1fd'
ROOT=Path(__file__).resolve().parent

def replace_once(text,old,new):
    if text.count(old)!=1:raise ValueError('Unexpected QEMU source seam')
    return text.replace(old,new,1)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--qemu-repo',type=Path,required=True);a=p.parse_args()
    repo=a.qemu_repo.resolve()
    if subprocess.check_output(['git','rev-parse','HEAD'],cwd=repo,text=True).strip()!=BASE:
        p.error('Use the exact pinned Z8 model checkout')
    names=['qemu/nikon-z8-lab.c','qemu/nikon-z8-pixels.h','tests/test_capture_drain.py']
    old={n:subprocess.check_output(['git','show',BASE+':'+n],cwd=repo) for n in names}
    text={n:b.decode() for n,b in old.items()}
    c=names[0];s=text[c]
    s=replace_once(s,'    uint64_t engine1543_retained_starts;','    uint64_t engine1543_retained_starts;\n    bool og4k_header_model, og4k_header_wait;\n    uint32_t og4k_header_rejected;\n    uint64_t og4k_header_starts, og4k_header_releases;')
    s=replace_once(s,'static bool engine1543_control_write(', '#include "nikon-z8-og4k-header.h"\n\nstatic bool engine1543_control_write(')
    s=replace_once(s,'    bool video = current_video || retained_video;', '    bool early_video = mode==1 && !current_video && !retained_video && og4k_header_start(s,j,value);\n    bool video = current_video || retained_video || early_video;')
    s=replace_once(s,'        if (retained_video) { s->engine1543_retained_starts++; }', '        if (retained_video) { s->engine1543_retained_starts++; }\n        if (early_video) { s->og4k_header_wait=true; s->og4k_header_starts++; }')
    s=replace_once(s,'        s->engine1543_active[j] = s->engine1543_held[j] = false;\n    } else if (mode == 2', '        s->engine1543_active[j] = s->engine1543_held[j] = false;\n        if (j==1) { s->og4k_header_wait=false; }\n    } else if (mode == 2')
    anchor='    g_string_truncate(out,out->len-1);g_string_append(out,",\\\"video_input\\\":{\\\"supplier\\\":");'
    extra='''    g_string_truncate(out,out->len-1);
    g_string_append_printf(out, ",\\\"early_video\\\":{\\\"enabled\\\":%s,\\\"waiting\\\":%s,\\\"rejected\\\":%u,\\\"starts\\\":%" PRIu64 ",\\\"releases\\\":%" PRIu64 ",\\\"physical_verified\\\":false}",
        s->og4k_header_model?"true":"false",s->og4k_header_wait?"true":"false",s->og4k_header_rejected,s->og4k_header_starts,s->og4k_header_releases);
    g_string_append(out,",\\\"video_input\\\":{\\\"supplier\\\":");'''
    s=replace_once(s,anchor,extra)
    anchor='    object_class_property_add_bool(oc,"engine1543-retained-start-model",get_engine1543_retained_start_model,set_engine1543_retained_start_model);'
    s=replace_once(s,anchor,anchor+'\n    object_class_property_add_bool(oc,"og4k-header-model",get_og4k_header_model,set_og4k_header_model);')
    text[c]=s
    # Keep the upstream timer rearm before a waiting control latch returns.
    # Otherwise one deferred tick permanently removes its own retry source.
    text[names[1]]=replace_once(text[names[1]],'    bool internal = video && s->video_raw_transport_model;',
        '    /* Receiver control latch is not pixel readiness; preserve timer rearm. */\n    if (!og4k_header_poll(s)) { return; }\n    bool internal = video && s->video_raw_transport_model;')
    t=names[2];s=text[t]
    s=replace_once(s,' uint64_t capture_stream_rearms,engine1543_retained_starts;', ' uint64_t capture_stream_rearms,engine1543_retained_starts;\n bool og4k_header_wait; uint64_t og4k_header_starts;')
    anchor='static bool capture_stream_can_rearm('
    s=replace_once(s,anchor,'static bool og4k_header_start(NikonZ8State*s,unsigned j,uint64_t v){(void)s;(void)j;(void)v;return false;}\n'+anchor)
    text[t]=s
    changes={n:s.encode() for n,s in text.items()}
    header='qemu/nikon-z8-og4k-header.h';changes[header]=(ROOT/'deferred_header.h').read_bytes()
    for n,data in changes.items():
        target=repo/n
        if target.exists() and target.read_bytes()!=data and (n not in old or target.read_bytes()!=old[n]):
            raise ValueError('Preserve and review existing model changes: '+n)
    for n,data in changes.items():(repo/n).write_bytes(data)
    print('Applied explicit default-off control model; firmware and readiness checks retained.')
    for n,data in changes.items():print(n,hashlib.sha256(data).hexdigest())

if __name__=='__main__':main()
