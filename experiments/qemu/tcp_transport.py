# SPDX-License-Identifier: GPL-2.0-or-later
# Host transport initialization adapted from WonderLantern/z8-qemu,
# Copyright (C) 2026 RdWing. Guest logic and device properties are unchanged.
"""Loopback-only QMP/GDB/qtest transport for hosts without Unix sockets."""
import json
import socket
import subprocess
import time
from full_guest import Guest as UpstreamGuest
from probe import QMP as UpstreamQMP

class TCPQMP(UpstreamQMP):
    def __init__(self,connection):
        self.sock=connection;self.sock.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
        self.sock.settimeout(3);self.fp=self.sock.makefile('rwb',buffering=0);self.events=[]
        self.greeting=json.loads(self.fp.readline());self.command('qmp_capabilities')

class TCPGuest(UpstreamGuest):
    def __enter__(self):
        started=time.monotonic();reservations=[];ports={}
        try:
            for option in ('-qmp','-gdb','-qtest'):
                sock=socket.socket(socket.AF_INET,socket.SOCK_STREAM);sock.bind(('127.0.0.1',0))
                ports[option]=sock.getsockname()[1];reservations.append(sock)
                self.command[self.command.index(option)+1]=f'tcp:127.0.0.1:{ports[option]},server=on,wait=off,nodelay=on'
            self.data['command']=self.command
            self.data['host_transport']=dict(kind='tcp',bind='127.0.0.1',ports=ports,guest_changes=False)
            self.uart_path=self.log_path.with_name('uart-tx.log')
            for sock in reservations:sock.close()
            with self.uart_path.open('xb') as uart,self.log_path.open('xb') as log:
                self.proc=subprocess.Popen(self.command,stdout=uart,stderr=log)
            self.data['uart_tx']=dict(path=str(self.uart_path),source='MAIN UART TX, combined channels',receive_supported=False)
            while True:
                cancel=getattr(self,'startup_cancelled',None)
                if cancel and cancel():raise InterruptedError('QEMU startup cancelled')
                if self.proc.poll() is not None:raise RuntimeError('QEMU exited during startup; see stderr.log')
                try:connection=socket.create_connection(('127.0.0.1',ports['-qmp']),timeout=.2);break
                except (ConnectionRefusedError,TimeoutError):
                    if time.monotonic()-started>10:raise RuntimeError('QEMU QMP startup timeout')
                    time.sleep(.02)
            self.data['qemu_startup_seconds']=round(time.monotonic()-started,6);self.qmp=TCPQMP(connection)
            self.qt=socket.create_connection(('127.0.0.1',ports['-qtest']),timeout=3)
            self.qt.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1);self.fp=self.qt.makefile('rwb',buffering=0)
            if self.accelerator!='qtest':
                self.gdb=socket.create_connection(('127.0.0.1',ports['-gdb']),timeout=3)
                self.gdb.setsockopt(socket.IPPROTO_TCP,socket.TCP_NODELAY,1)
            if self.intercept_irq:
                children=self.qmp.command('qom-list',path='/machine/unattached')
                gics=[x for x in children if x['type']=='child<arm-gicv3>']
                if len(gics)!=1:raise RuntimeError('GIC object not unique')
                self.qt_command('irq_intercept_in /machine/unattached/'+gics[0]['name'])
            if self.accelerator!='qtest':self.rsp('Z1,40160000,4')
            return self
        except BaseException as exc:
            self.data['qemu_startup_failure']=dict(elapsed_seconds=round(time.monotonic()-started,6),message=str(exc))
            self.__exit__(type(exc),exc,None);raise
        finally:
            for sock in reservations:sock.close()
