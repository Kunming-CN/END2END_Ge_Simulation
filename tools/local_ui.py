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
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser

from local_ui_jobs import BASE, Controller, ControlError, decode_json
from local_ui_gamma_jobs import GammaController
from local_ui_scenarios import checked_scenarios
from local_ui_workflow_jobs import WorkflowController
import scenario_workflow as workflow

ROOT = Path(__file__).resolve().parents[1]
STATE = '.local/local-control-v1'
STATIC = {'/': ('local_workflow.html', 'text/html; charset=utf-8'),
          '/local_workflow.js': ('local_workflow.js', 'text/javascript; charset=utf-8'),
          '/local_ui.js': ('local_workflow.js', 'text/javascript; charset=utf-8')}
FILES = {'run.json', 'COMPLETE.json', 'manifest.json', 'worker/report.json',
         'worker/AK02/scalars.jsonl', 'worker/AK02/traces.jsonl',
         'worker/SAP22/scalars.jsonl', 'worker/SAP22/traces.jsonl'}


class SavedGammaUnavailable(RuntimeError):
    pass


class SavedGammaOpenError(RuntimeError):
    pass


def open_saved_gamma_example():
    """Check the fixed completed bundle, then request its existing offline viewer."""
    try:
        from gamma_showcase import validate_bundle
        bundle = ROOT / '.local/m11d-gamma-showcase-v1/bundle'
        data = validate_bundle(bundle)
        counts = data['science']['source']['counts']
        expected = {'radiation_primaries': 40, 'selected_primaries': 6,
                    'unprocessed_primaries': 34}
        census = {key: counts[key] for key in expected}
        if any(type(value) is not int for value in census.values()) or census != expected:
            raise ValueError('Unsupported saved example census')
        target = (bundle / 'gamma.html').as_uri()
    except Exception:
        raise SavedGammaUnavailable from None
    try:
        if not webbrowser.open(target):
            raise SavedGammaOpenError
    except Exception:
        raise SavedGammaOpenError from None
    return {'kind': 'saved_gamma_example_open_v1', 'status': 'browser_open_requested',
            'science_calls': 0, 'census': census}


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

    def __init__(self, port, controller, token=None, *, gamma_controller=None, workflow_controller=None):
        super().__init__(('127.0.0.1', port), Handler)
        self.controller = controller
        self.gamma_controller = gamma_controller
        self.workflow_controller = workflow_controller
        self.token = token or secrets.token_urlsafe(32)
        # Separate read-only session capability; never authorizes state or writes.
        # Loopback cookies are not isolated by port. Exact origin/fetch-site guards
        # remain required, and a random name avoids stale-instance collisions.
        self.download_cookie = 'ge_download_' + secrets.token_hex(12)
        self.download_token = secrets.token_urlsafe(32)
        self.gamma_download_cookie = 'ge_gamma_download_' + secrets.token_hex(12)
        self.gamma_download_token = secrets.token_urlsafe(32)
        self.workflow_download_cookie = 'ge_workflow_download_' + secrets.token_hex(12)
        self.workflow_download_token = secrets.token_urlsafe(32)
        self.origin = 'http://127.0.0.1:' + str(self.server_port)
        self.static_root = ROOT / 'tools'


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass  # Requests may contain private run identities; no URL/access log.

    def send_data(self, status, body, content_type='application/json; charset=utf-8', filename=None, grant_download=False, grant_gamma_download=False, grant_workflow_download=False):
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
        if grant_gamma_download:
            self.send_header('Set-Cookie', self.server.gamma_download_cookie + '=' + self.server.gamma_download_token +
                             '; Path=/api/gamma-file; HttpOnly; SameSite=Strict')
        if grant_workflow_download:
            self.send_header('Set-Cookie', self.server.workflow_download_cookie + '=' + self.server.workflow_download_token +
                             '; Path=/api/workflow-file; HttpOnly; SameSite=Strict')
        self.end_headers()
        self.wfile.write(body)
        self.close_connection = True

    def reject(self, code, message):
        self.send_data(code, {'error': message})

    def authorized(self, write=False, download=False, gamma_download=False, workflow_download=False):
        if self.headers.get('Host') != urlsplit(self.server.origin).netloc:
            self.reject(403, 'Loopback host required'); return False
        origin = self.headers.get('Origin')
        if (write and origin != self.server.origin) or (origin and origin != self.server.origin):
            self.reject(403, 'Same origin required'); return False
        if self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
            self.reject(403, 'Same origin required'); return False
        bearer_ok = secrets.compare_digest(self.headers.get('X-Control-Token', '').encode('utf-8'), self.server.token.encode('utf-8'))
        cookie_ok = False
        if (download or gamma_download or workflow_download) and not write and self.headers.get('Sec-Fetch-Site') == 'same-origin':
            try:
                cookie = SimpleCookie(self.headers.get('Cookie', ''))
                name = self.server.workflow_download_cookie if workflow_download else self.server.gamma_download_cookie if gamma_download else self.server.download_cookie
                token = self.server.workflow_download_token if workflow_download else self.server.gamma_download_token if gamma_download else self.server.download_token
                value = cookie.get(name)
                cookie_ok = bool(value) and secrets.compare_digest(value.value.encode('utf-8'), token.encode('utf-8'))
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
        if not self.authorized(download=parts.path == '/api/file', gamma_download=parts.path == '/api/gamma-file', workflow_download=parts.path in ('/api/workflow-file','/api/workflow-file/plots')):
            return
        try:
            if parts.path == '/api/workflow-file/plots':
                import re
                if parts.fragment:raise ValueError('Invalid waveform artifact fragment')
                query=parse_qs(parts.query,strict_parsing=True)
                if set(query)!={'name','primary','group'} or any(len(v)!=1 for v in query.values()) or self.server.workflow_controller is None:
                    raise ValueError('Invalid exact waveform request')
                primary=query['primary'][0];group=query['group'][0]
                if not re.fullmatch(r'0|[1-9]\d{0,9}',primary) or not (group=='none' or re.fullmatch(r'0|[1-9]\d{0,9}',group)):
                    raise ValueError('Invalid exact waveform identity')
                if int(primary)>2147483646 or group!='none' and int(group)>2147483646:
                    raise ValueError('Invalid exact waveform identity')
                return self.send_data(200,self.server.workflow_controller.waveforms(
                    query['name'][0],int(primary),None if group=='none' else int(group)))
            if parts.path in ('/api/workflow/catalog','/api/workflow/setup','/api/workflow/state'):
                if self.path!=parts.path:return self.reject(404,'Unknown workflow route')
                if self.server.workflow_controller is None:
                    return self.reject(503, 'Workflow control is unavailable')
                method = {'/api/workflow/catalog': lambda: workflow.catalog(),
                          '/api/workflow/setup': self.server.workflow_controller.setup,
                          '/api/workflow/state': self.server.workflow_controller.snapshot}[parts.path]
                return self.send_data(200, method(),grant_workflow_download=True)
            if parts.path == '/api/workflow-file':
                if parts.fragment:raise ValueError('Invalid workflow artifact fragment')
                query=parse_qs(parts.query,strict_parsing=True)
                if set(query)!={'name','file'} or any(len(v)!=1 for v in query.values()) or self.server.workflow_controller is None:
                    raise ValueError('Invalid workflow artifact request')
                body,mime=self.server.workflow_controller.artifact(query['name'][0],query['file'][0])
                if mime.startswith('text/html'):
                    # Derived navigation only; original downloaded science bytes remain exact.
                    import posixpath
                    import re
                    from urllib.parse import urlencode
                    base=posixpath.dirname(query['file'][0])
                    def link(match):
                        ref=match.group(2)
                        if ':' in ref or ref.startswith(('/', '#')):
                            return match.group(0)
                        target=posixpath.normpath(posixpath.join(base,ref))
                        return 'href='+match.group(1)+'/api/workflow-file?'+urlencode({'name':query['name'][0],'file':target})+match.group(1)
                    document=re.sub(r'href=([\'\"])([^\'\"]+)\1',link,body.decode('utf-8'))
                    document=re.sub(r'<details><summary>Event (\d+) / group (\d+|nothing)</summary>',
                        lambda m:'<details id="event-'+m[1]+'-group-'+('none' if m[2]=='nothing' else m[2])+'"><summary>Event '+m[1]+' / group '+m[2]+'</summary>',document)
                    body=document.encode('utf-8')
                return self.send_data(200,body,mime)
            if self.path == '/api/scenarios':
                try:
                    return self.send_data(200, checked_scenarios())
                except Exception:
                    return self.reject(503, 'Scenario configuration preview is unavailable')
            if self.path == '/api/state':
                state = self.server.controller.snapshot()
                if self.server.gamma_controller is not None:
                    state['gamma'] = self.server.gamma_controller.snapshot()
                return self.send_data(200, state, grant_download=True)
            if parts.path == '/api/gamma-file':
                if parts.fragment:
                    raise ValueError('Invalid Gamma result request')
                query = parse_qs(parts.query, strict_parsing=True)
                if set(query) != {'job_id', 'file'} or any(len(v) != 1 for v in query.values()) or self.server.gamma_controller is None:
                    raise ValueError('Invalid Gamma result request')
                body, filename = self.server.gamma_controller.download(query['job_id'][0], query['file'][0])
                return self.send_data(200, body, 'application/octet-stream', filename)
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
            data = decode_json(self.rfile.read(size).decode('utf-8'))
            workflow_routes={'/api/workflow/check':({'config'},'check'),
                             '/api/workflow/start':({'check_id'},'start'),
                             '/api/workflow/stop':({'name'},'stop'),
                             '/api/workflow/resume':({'name'},'resume'),
                             '/api/workflow/inspect-failure':({'name'},'inspect_failure'),
                             '/api/workflow/continue-prefix':({'name','new_name'},'continue_prefix'),
                             '/api/workflow/finalize-results':({'name'},'finalize_results'),
                             '/api/workflow/verify':({'name'},'verify')}
            if self.path in workflow_routes:
                keys,method=workflow_routes[self.path]
                if type(data) is not dict or set(data)!=keys or self.server.workflow_controller is None:
                    raise ValueError('Unsupported workflow input fields')
                if method=='check':
                    if type(data['config']) is not dict:raise ValueError('Configuration must be a JSON object')
                elif any(type(v) is not str for v in data.values()):
                    raise ValueError('Workflow identities must be strings')
                return self.send_data(200,getattr(self.server.workflow_controller,method)(**data))
            if self.path == '/api/open-saved-gamma':
                if type(data) is not dict or data:
                    raise ValueError('Unsupported input fields or types')
                try:
                    return self.send_data(200, open_saved_gamma_example())
                except SavedGammaUnavailable:
                    return self.reject(503, 'Saved gamma example is unavailable')
                except SavedGammaOpenError:
                    return self.reject(503, 'Saved gamma example open request failed')
            gamma_routes = {'/api/gamma-check': ({'threads'}, 'check'),
                            '/api/gamma-start': ({'check_id'}, 'start'),
                            '/api/gamma-verify': ({'job_id'}, 'verify')}
            if self.path in gamma_routes:
                keys, method = gamma_routes[self.path]
                if (type(data) is not dict or set(data) != keys or
                        (method == 'check' and (type(data['threads']) is not int or data['threads'] not in (1, 2))) or
                        (method != 'check' and any(type(v) is not str for v in data.values()))):
                    raise ValueError('Unsupported input fields or types')
                if self.server.gamma_controller is None:
                    return self.reject(503, 'Gamma control is unavailable')
                if method=='start' and self.server.workflow_controller is not None:
                    with self.server.workflow_controller.scientific_entry():result=getattr(self.server.gamma_controller,method)(**data)
                else:result = getattr(self.server.gamma_controller, method)(**data)
                return self.send_data(200, result, grant_gamma_download=True)
            routes = {'/api/check': ({'name', 'detector'}, 'check'),
                      '/api/start': ({'name', 'detector'}, 'start'),
                      '/api/stop': ({'job_id'}, 'stop'), '/api/resume': ({'name'}, 'resume')}
            if self.path not in routes:
                return self.reject(404, 'Unknown local action')
            keys, method = routes[self.path]
            if type(data) is not dict or set(data) != keys or any(type(v) is not str for v in data.values()):
                raise ValueError('Unsupported input fields or types')
            if method in ('start','resume') and self.server.workflow_controller is not None:
                with self.server.workflow_controller.scientific_entry():result=getattr(self.server.controller,method)(**data)
            else:result = getattr(self.server.controller, method)(**data)
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
        coordination = threading.RLock()
        controller = Controller(ROOT, coordination_lock=coordination)
        gamma = GammaController(ROOT, coordination_lock=coordination, peer_busy=controller.own_busy)
        configured=WorkflowController(ROOT,coordination_lock=coordination,
                                      peer_busy=lambda: controller.own_busy() or gamma.own_busy())
        controller.set_peer_busy(lambda: gamma.own_busy() or configured.own_busy())
        gamma.set_peer_busy(lambda: controller.own_busy() or configured.own_busy())
        server = Server(args.port, controller, gamma_controller=gamma, workflow_controller=configured)
        session = server.origin + '/#' + server.token
        receipt = folder / 'server.json'
        receipt.write_text(json.dumps({'pid': os.getpid(), 'url': session, 'origin': server.origin}, indent=2), encoding='utf-8')
        print('Local control: ' + server.origin + ' (session link opens in your browser).', flush=True)
        print('Keep this terminal open. Stop waits for the current workflow stage; incomplete or uncertain workers are preserved for inspection.', flush=True)
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
