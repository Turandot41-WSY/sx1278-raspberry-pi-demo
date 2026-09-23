"""Serve the local receiver display without exposing design writes."""

from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse

from host.display.receiver import ReceiverStore

WEB = Path(__file__).resolve().parents[2] / 'web'


class DisplayHandler(SimpleHTTPRequestHandler):
    """Expose local display assets and read-only telemetry endpoints."""

    def __init__(self, *args, **kwargs):
        """Restrict static responses to the maintained display assets.

        Direct call tree (static source order):
            __init__
            +-- super
            +-- super(...).__init__
            `-- str
        """
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, format, *args):
        """Keep periodic browser requests out of the radio operator console.

        Direct call tree (static source order):
            log_message
            `-- [no direct function calls; local state/return only]
        """

    def reply(self, value):
        """Send one uncached telemetry response.

        Direct call tree (static source order):
            reply
            +-- json.dumps
            +-- json.dumps(...).encode
            +-- self.send_response
            +-- self.send_header
            +-- str
            +-- len
            +-- self.end_headers
            `-- self.wfile.write
        """
        data = json.dumps(value, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        """Return the receiver view, receiver telemetry or a public asset.

        References:
            Python 3 library reference, http.server, SimpleHTTPRequestHandler
            do_GET and directory parameter; https://docs.python.org/3/library/http.server.html

        Processing flow:
            Route display URL -> read telemetry or page metadata -> serve asset;
            requests for an unknown API or directory are rejected.

        Direct call tree (static source order):
            do_GET
            +-- urlparse
            +-- self.send_response
            +-- self.send_header
            +-- self.end_headers
            +-- super
            +-- super(...).do_GET
            +-- self.reply
            +-- parse_qs
            +-- parse_qs(...).get
            +-- self.server.receiver.snapshot
            +-- parsed.path.startswith
            `-- self.send_error
        """
        parsed = urlparse(self.path)
        if parsed.path in ('/', '/index.html'):
            self.send_response(302)
            self.send_header('Location', '/monitor')
            self.end_headers()
        elif parsed.path == '/monitor':
            self.path = '/index.html'
            super().do_GET()
        elif parsed.path == '/api/scene':
            self.reply({'scene': self.server.scene})
        elif parsed.path == '/api/region':
            self.reply(self.server.receiver.reference.region)
        elif parsed.path == '/api/telemetry':
            selected = parse_qs(parsed.query).get('source', ['latest'])[0]
            self.reply(self.server.receiver.snapshot(selected))
        elif parsed.path.startswith('/api/'):
            self.send_error(404, 'Unknown endpoint')
        else:
            super().do_GET()

    def list_directory(self, path):
        """Reject directory listings; only named display assets are served.

        Direct call tree (static source order):
            list_directory
            `-- self.send_error
        """
        self.send_error(404, 'Not found')
        return None

    def do_POST(self):
        """Reject writes because the operational page cannot edit the design.

        Direct call tree (static source order):
            do_POST
            `-- self.send_error
        """
        self.send_error(405, 'The receiver display is read-only')


def create_server(port, receive_root, reference_dataset, events=None):
    """Validate the local reference before binding the browser display port.

    References:
        Python 3 library reference, http.server.ThreadingHTTPServer constructor;
        https://docs.python.org/3/library/http.server.html#http.server.ThreadingHTTPServer

    Processing flow:
        Validate frozen orbit -> prepare local page metadata -> bind loopback HTTP
        -> attach read-only log store and scene.

    Direct call tree (static source order):
        create_server
        +-- ReceiverStore
        +-- json.loads
        +-- <BinOp expression>.read_text
        `-- ThreadingHTTPServer
    """
    receiver = ReceiverStore(receive_root, reference_dataset, events)
    scene = json.loads((WEB / 'approved-scene.json').read_text(encoding='utf-8'))
    server = ThreadingHTTPServer(('127.0.0.1', port), DisplayHandler)
    server.receiver = receiver
    server.scene = scene
    return server


class DisplayService:
    """Own the HTTP worker used alongside a serial receive session."""

    def __init__(self, server):
        """Keep the bound server and one worker for deterministic cleanup.

        Direct call tree (static source order):
            __init__
            `-- threading.Thread
        """
        self.server = server
        self.worker = threading.Thread(target=server.serve_forever, daemon=True)

    def start(self):
        """Start the local page service without opening a foreground browser.

        Direct call tree (static source order):
            start
            +-- self.worker.start
            `-- print
        """
        self.worker.start()
        print(f'Receiver display: http://127.0.0.1:{self.server.server_port}/monitor', flush=True)

    def close(self):
        """Stop the worker and release its listening socket.

        References:
            Python 3 library reference, socketserver.BaseServer.shutdown:
            call shutdown from a different thread than serve_forever;
            https://docs.python.org/3/library/socketserver.html#socketserver.BaseServer.shutdown

        Processing flow:
            Stop active worker -> release socket -> join the owned worker.

        Direct call tree (static source order):
            close
            +-- self.worker.is_alive
            +-- self.server.shutdown
            +-- self.server.server_close
            `-- self.worker.join
        """
        if self.worker.is_alive():
            self.server.shutdown()
        self.server.server_close()
        if self.worker.ident is not None:
            self.worker.join(timeout=5)
