"""Session-protected loopback control of the unchanged bounded native backend."""
import argparse
from contextlib import contextmanager
import hashlib
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import secrets
import stat
import sys
from urllib.parse import parse_qs, urlsplit
import webbrowser

from local_ui_jobs import BASE, Controller, ControlError
from local_ui_scenarios import checked_scenarios

ROOT = Path(__file__).resolve().parents[1]
STATE = '.local/local-control-v1'
STATIC = {'/': ('local_ui.html', 'text/html; charset=utf-8'),
          '/local_ui.js': ('local_ui.js', 'text/javascript; charset=utf-8')}
FILES = {'run.json', 'COMPLETE.json', 'manifest.json', 'worker/report.json',
         'worker/AK02/scalars.jsonl', 'worker/AK02/traces.jsonl',
         'worker/SAP22/scalars.jsonl', 'worker/SAP22/traces.jsonl'}


def guarded(root, relative):
    """Reject traversal/reparse components before reads and writes."""
    root = Path(root).absolute()
    bits = relative.replace('\\', '/').split('/')
    if not bits or any(b in ('', '.', '..') or ':' in b for b in bits):
        raise ValueError('Unsafe local path')
    current = root
    for bit in bits:
        current = current / bit
        try:
            info = current.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT:
            raise ValueError('Reparse paths are not supported')
    if not current.resolve().is_relative_to(root.resolve()):
        raise ValueError('Local path escapes project')
    return current


@contextmanager
def server_lease(root):
    folder = guarded(root, STATE)
    folder.mkdir(parents=True, exist_ok=True)
    path = guarded(root, STATE + '/server.lock')
    with path.open('a+b') as stream:
        stream.seek(0, 2)
        if stream.tell() == 0:
            stream.write(b'0'); stream.flush()
        stream.seek(0)
        if os.name == 'nt':
            import msvcrt
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise RuntimeError('Local control is already open; use its existing browser window.') from error
        else:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            yield folder
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port, controller, token=None):
        super().__init__(('127.0.0.1', port), Handler)
        self.controller = controller
        self.token = token or secrets.token_urlsafe(32)
        # Separate read-only session capability; never authorizes state or writes.
        # Loopback cookies are not isolated by port. Exact origin/fetch-site guards
        # remain required, and a random name avoids stale-instance collisions.
        self.download_cookie = 'ge_download_' + secrets.token_hex(12)
        self.download_token = secrets.token_urlsafe(32)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)
        self.static_root = ROOT / 'tools'


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass  # Requests may contain private run identities; no URL/access log.

    def send_data(self, status, body, content_type='application/json; charset=utf-8', filename=None, grant_download=False):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False, allow_nan=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'")
        self.send_header('Connection', 'close')
        if filename:
            self.send_header('Content-Disposition', 'attachment; filename="' + filename + '"')
        if grant_download:
            self.send_header('Set-Cookie', self.server.download_cookie + '=' + self.server.download_token +
                             '; Path=/api/file; HttpOnly; SameSite=Strict')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def reject(self, code, message):
        self.send_data(code, {'error': message})

    def authorized(self, write=False, download=False):
        if self.headers.get('Host') != urlsplit(self.server.origin).netloc:
            self.reject(403, 'Loopback host required'); return False
        origin = self.headers.get('Origin')
        if (write and origin != self.server.origin) or (origin and origin != self.server.origin):
            self.reject(403, 'Same origin required'); return False
        if self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
            self.reject(403, 'Same origin required'); return False
        bearer_ok = secrets.compare_digest(self.headers.get('X-Control-Token', '').encode('utf-8'), self.server.token.encode('utf-8'))
        cookie_ok = False
        if download and not write and self.headers.get('Sec-Fetch-Site') == 'same-origin':
            try:
                cookie = SimpleCookie(self.headers.get('Cookie', ''))
                value = cookie.get(self.server.download_cookie)
                cookie_ok = bool(value) and secrets.compare_digest(value.value.encode('utf-8'), self.server.download_token.encode('utf-8'))
            except CookieError:
                pass
        if not bearer_ok and not cookie_ok:
            self.reject(403, 'Open the session link from Control.cmd'); return False
        return True

    def do_GET(self):
        parts = urlsplit(self.path)
        if self.headers.get('Host') != urlsplit(self.server.origin).netloc:
            return self.reject(403, 'Loopback host required')
        if parts.path in STATIC and not parts.query:
            name, mime = STATIC[parts.path]
            return self.send_data(200, (self.server.static_root / name).read_bytes(), mime)
        if not self.authorized(download=parts.path == '/api/file'):
            return
        try:
            if self.path == '/api/scenarios':
                try:
                    return self.send_data(200, checked_scenarios())
                except Exception:
                    return self.reject(503, 'Scenario configuration preview is unavailable')
            if parts.path == '/api/state' and not parts.query:
                return self.send_data(200, self.server.controller.snapshot(), grant_download=True)
            if parts.path == '/api/file':
                query = parse_qs(parts.query, strict_parsing=True)
                if set(query) != {'name', 'file'} or any(len(v) != 1 for v in query.values()):
                    raise ValueError('Invalid result request')
                name, artifact = query['name'][0], query['file'][0]
                # Only controller-owned, terminal verified runs are downloadable.
                jobs = self.server.controller.snapshot()['jobs']
                job = next((j for j in jobs if j['name'] == name and j['status'] in ('completed', 'completed_with_native_failures')), None)
                if not job or not job.get('complete_sha256'):
                    raise ValueError('Only verified results from this control session are available')
                if artifact not in FILES:
                    raise ValueError('Unsupported result file')
                import re
                if not re.fullmatch('[A-Za-z0-9_-]{1,24}', name):
                    raise ValueError('Invalid run name')
                path = guarded(self.server.controller.root, BASE + '/' + name + '/' + artifact)
                if path.stat().st_size > 8 * 1024 * 1024:
                    raise ValueError('Result exceeds bounded download size')
                complete_bytes = guarded(self.server.controller.root, BASE + '/' + name + '/COMPLETE.json').read_bytes()
                if hashlib.sha256(complete_bytes).hexdigest() != job['complete_sha256']:
                    raise ValueError('Completed result receipt changed; download refused')
                complete = json.loads(complete_bytes)
                body = path.read_bytes()
                stamp = complete['artifacts'].get(artifact)
                expected_hash = (job['complete_sha256'] if artifact == 'COMPLETE.json' else
                    complete['manifest_sha256'] if artifact == 'manifest.json' else stamp['sha256'] if stamp else None)
                if not expected_hash or hashlib.sha256(body).hexdigest() != expected_hash or (stamp and len(body) != stamp['bytes']):
                    raise ValueError('Completed artifact changed; download refused')
                return self.send_data(200, body, 'application/octet-stream', name + '-' + artifact.replace('/', '-'))
            return self.reject(404, 'Unknown local route')
        except (ValueError, OSError, ControlError) as error:
            return self.reject(400, str(error) if isinstance(error, (ValueError, ControlError)) else 'Result file is unavailable')

    def do_POST(self):
        if not self.authorized(write=True):
            return
        try:
            if self.headers.get('Content-Type') != 'application/json':
                raise ValueError('JSON request required')
            if self.headers.get('Transfer-Encoding'):
                raise ValueError('Chunked requests are not supported')
            size = int(self.headers.get('Content-Length', '-1'))
            if not 1 <= size <= 4096:
                raise ValueError('Request size must be 1..4096 bytes')
            data = json.loads(self.rfile.read(size))
            routes = {'/api/check': ({'name', 'detector'}, 'check'),
                      '/api/start': ({'name', 'detector'}, 'start'),
                      '/api/stop': ({'job_id'}, 'stop'), '/api/resume': ({'name'}, 'resume')}
            if self.path not in routes:
                return self.reject(404, 'Unknown local action')
            keys, method = routes[self.path]
            if type(data) is not dict or set(data) != keys or any(type(v) is not str for v in data.values()):
                raise ValueError('Unsupported input fields or types')
            result = getattr(self.server.controller, method)(**data)
            return self.send_data(200, result)
        except (ValueError, ControlError) as error:
            return self.reject(400, str(error))
        except Exception:
            return self.reject(500, 'Local action failed; inspect the saved local control evidence')

    def do_OPTIONS(self):
        self.reject(403, 'Cross-origin control is disabled')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=0)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser.error('Port must be 0..65535')
    with server_lease(ROOT) as folder:
        server = Server(args.port, Controller(ROOT))
        session = server.origin + '/#' + server.token
        receipt = folder / 'server.json'
        receipt.write_text(json.dumps({'pid': os.getpid(), 'url': session, 'origin': server.origin}, indent=2), encoding='utf-8')
        print('Local control: ' + server.origin + ' (session link opens in your browser).', flush=True)
        print('Closing this terminal stops the interface. Stop an active job in the page first.', flush=True)
        if not args.no_browser:
            webbrowser.open(session)
        try:
            server.serve_forever(poll_interval=0.5)
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
            # Keep scientific/job records; remove only this ephemeral session secret.
            receipt.unlink(missing_ok=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
