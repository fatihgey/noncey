#!/usr/bin/env python3
"""
Minimal HTTP server for the noncey extension smoke test.
Serves tests/client.chromeextension/testpage/ on localhost.

Usage:
  python3 testserver.py          # port 18080 (default)
  python3 testserver.py 19000    # custom port
"""

import http.server
import sys
from pathlib import Path

PORT      = int(sys.argv[1]) if len(sys.argv) > 1 else 18080
SERVE_DIR = Path(__file__).parent / 'testpage'


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SERVE_DIR), **kwargs)

    def log_message(self, fmt, *args):
        pass  # silence per-request log noise


if __name__ == '__main__':
    with http.server.HTTPServer(('127.0.0.1', PORT), Handler) as srv:
        print(f'noncey testserver: http://127.0.0.1:{PORT}', flush=True)
        srv.serve_forever()
