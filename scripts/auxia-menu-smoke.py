#!/usr/bin/env python3
import os
import pathlib
import pty
import select
import subprocess
import sys
import tempfile
import termios
import time

binary=pathlib.Path(sys.argv[1]).resolve()
with tempfile.TemporaryDirectory() as temp:
    env={**os.environ,'XDG_CONFIG_HOME':temp,'TERM':'xterm-256color'}
    env.pop('CODEZ_SIMPLE_UI',None)
    master,slave=pty.openpty()
    original=termios.tcgetattr(slave)
    proc=subprocess.Popen([str(binary),'--auxia'],stdin=slave,stdout=slave,stderr=slave,env=env)
    try:
        output=b''; deadline=time.monotonic()+10
        while b'Sign in with Auxia account' not in output and time.monotonic()<deadline:
            if select.select([master],[],[],0.2)[0]: output+=os.read(master,8192)
        assert b'Auxia / Connect' in output and b'Sign in with Auxia account' in output,output
        os.write(master,b'\x1b[B\r')
        assert proc.wait(timeout=5)==0
        assert termios.tcgetattr(slave)==original
        assert not (pathlib.Path(temp)/'codez'/'auxia-session').exists()
        print('PASS: Auxia login selector, Back navigation, no AI provider required, terminal restoration')
    finally:
        if proc.poll() is None: proc.kill();proc.wait()
        os.close(master);os.close(slave)
