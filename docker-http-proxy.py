#!/usr/bin/env python3
import http.server
import socketserver
import urllib.request
import os

SYSTEM_DOCKER = 'http+unix://%2Fvar%2Frun%2Fdocker.sock'
PORT = 2376

class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self): self._f()
    def do_POST(self): self._f()
    def do_PUT(self): self._f()
    def do_DELETE(self): self._f()
    def _f(self):
        length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(length) if length else None
        req = urllib.request.Request(SYSTEM_DOCKER + self.path, data=body, method=self.command)
        resp = urllib.request.urlopen(req, timeout=30)
        self.send_response(resp.status)
        for k,v in resp.headers.items():
            if k.lower() not in ('transfer-encoding','connection'):
                self.send_header(k,v)
        self.end_headers()
        self.wfile.write(resp.read())
    def log_message(self, *a): pass

with socketserver.TCPServer(('127.0.0.1', PORT), Handler) as s:
    print(f"Docker proxy at http://127.0.0.1:{PORT}", flush=True)
    s.serve_forever()
