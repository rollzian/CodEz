#!/usr/bin/env python3
import errno
import http.server
import json
import os
import pathlib
import pty
import select
import subprocess
import sys
import tempfile
import termios
import threading
import time

binary = pathlib.Path(sys.argv[1]).resolve()

class Provider(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        assert self.path == '/v1/models'
        body = b'{"data":[{"id":"alpha"},{"id":"beta"}]}'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *args):
        pass

with tempfile.TemporaryDirectory() as temp:
    root = pathlib.Path(temp)
    env = {**os.environ, 'XDG_CONFIG_HOME': str(root/'config'), 'XDG_STATE_HOME': str(root/'state'), 'CODEZ_API_KEY': 'test-secret', 'TERM': 'xterm-256color'}
    env.pop('CODEZ_SIMPLE_UI', None)
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Provider)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    master, slave = pty.openpty()
    original = termios.tcgetattr(slave)
    proc = subprocess.Popen([str(binary)], stdin=slave, stdout=slave, stderr=slave, cwd=root, env=env)
    def until(marker):
        data = bytearray()
        deadline = time.monotonic()+10
        while marker not in data and time.monotonic()<deadline:
            if not select.select([master], [], [], .2)[0]:
                continue
            try:
                chunk = os.read(master, 16384)
            except OSError as e:
                if e.errno == errno.EIO:
                    break
                raise
            if not chunk:
                break
            data.extend(chunk)
        assert marker in data, bytes(data).decode(errors='replace')
        return data
    try:
        until(b'Connect your provider')
        os.write(master, b'\x1b[B\x1b[B\r')
        until(b'Endpoint')
        os.write(master, f'http://127.0.0.1:{server.server_port}/v1\n'.encode())
        until(b'Model library')
        os.write(master, b'\x1b[B\r')
        until(b'Provider configured')
        cfg = json.loads((root/'config'/'codez'/'config.json').read_text())
        assert cfg['model'] == 'beta', cfg
        assert cfg['provider'] == 'compatible', cfg
        os.write(master, b'/model\n')
        until(b'Model library')
        os.write(master, b'\x1b')
        until(b'selection cancelled')
        assert termios.tcgetattr(slave) == original
        os.write(master, b'/exit\n')
        assert proc.wait(timeout=5) == 0
        assert termios.tcgetattr(slave) == original
        print('PASS: TTY provider and model arrow navigation, Escape cancellation, terminal restoration')
    finally:
        if proc.poll() is None:
            proc.kill(); proc.wait()
        os.close(master); os.close(slave)
        server.shutdown(); server.server_close()
