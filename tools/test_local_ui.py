"""Real loopback protocol/security tests; no simulation or browser mocking claim."""
import hashlib
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

import local_ui as U


class FakeController:
    def __init__(self, root):
        self.root = root
        self.calls = []
        self.jobs = []

    def snapshot(self):
        return {'active': None, 'jobs': self.jobs, 'runs': []}

    def check(self, **values):
        self.calls.append(values)
        return {'status': 'planned', 'verification_final': True}


class Protocol(unittest.TestCase):
    def setUp(self):
        fixtures = U.ROOT / '.local/m11i-scenario-preview-v1/backend/test-fixtures'
        fixtures.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=fixtures)
        self.controller = FakeController(Path(self.temp.name))
        self.server = U.Server(0, self.controller, token='test-session-token')
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()
        self.temp.cleanup()

    def request(self, method='GET', route='/api/state', body=None, headers=None):
        base = {'Host': '127.0.0.1:' + str(self.server.server_port),
                'X-Control-Token': self.server.token}
        if method == 'POST':
            base.update(Origin=self.server.origin, **{'Content-Type':'application/json'})
        if headers:
            base.update(headers)
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        if isinstance(body, dict): body = json.dumps(body)
        connection.request(method, route, body=body, headers=base)
        response = connection.getresponse()
        result = (response.status, response.read(), dict(response.getheaders()))
        connection.close()
        return result

    def test_static_offline_assets_and_session_required(self):
        for route in ('/', '/local_ui.js'):
            code, data, headers = self.request(route=route, headers={'X-Control-Token':''})
            self.assertEqual(code, 200); self.assertTrue(data)
            self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertEqual(self.request(headers={'X-Control-Token':''})[0], 403)
        self.assertEqual(self.request(headers={'X-Control-Token':'wrong'})[0], 403)
        self.assertEqual(self.request()[0], 200)

    def test_rebinding_and_cross_origin_refusal(self):
        values = {'name':'new-run','detector':'AK02'}
        for headers in ({'Host':'evil.example'}, {'Host':'localhost:'+str(self.server.server_port)},
                        {'Origin':'https://evil.example'}, {'Sec-Fetch-Site':'cross-site'}, {'Origin':''}):
            self.assertEqual(self.request('POST','/api/check',values,headers)[0], 403)
        self.assertEqual(self.controller.calls, [])
        self.assertEqual(self.request('OPTIONS','/api/check')[0], 403)

    def test_scenario_catalog_authorized_no_query_and_no_controller_calls(self):
        code, data, headers = self.request(route='/api/scenarios')
        catalog = json.loads(data)
        self.assertEqual(code, 200)
        self.assertEqual(catalog['kind'], 'finite_scenario_preview_v1')
        self.assertEqual(len(catalog['scenarios']), 4)
        self.assertEqual(catalog['scientific_workers_launched'], 0)
        self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(headers['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(headers['Referrer-Policy'], 'no-referrer')
        self.assertIn("frame-ancestors 'none'", headers['Content-Security-Policy'])
        self.assertNotIn('Set-Cookie', headers)
        self.assertEqual(self.controller.calls, [])

    def test_scenario_auth_query_path_and_method_refusal_before_provider(self):
        with patch.object(U, 'checked_scenarios', side_effect=AssertionError('Provider called')) as provider:
            for headers in ({'X-Control-Token':''}, {'X-Control-Token':'wrong'}, {'Host':'evil.example'},
                            {'Host':'localhost:'+str(self.server.server_port)}, {'Origin':'https://evil.example'},
                            {'Sec-Fetch-Site':'cross-site'}, {'Sec-Fetch-Site':'same-site'}):
                self.assertEqual(self.request(route='/api/scenarios', headers=headers)[0], 403)
            for route in ('/api/scenarios?', '/api/scenarios?id=anything', '/api/scenarios?path=private',
                          '/api/scenarios?detector=AK02', '/api/scenarios/anything', '/api/scenarios/',
                          '/api/scenarios#selector'):
                self.assertEqual(self.request(route=route)[0], 404)
            self.assertEqual(self.request('POST', '/api/scenarios', {})[0], 404)
            self.assertEqual(self.request('OPTIONS', '/api/scenarios')[0], 403)
            self.assertEqual(self.request('HEAD', '/api/scenarios')[0], 501)
            self.assertEqual(self.request('PUT', '/api/scenarios', '{}')[0], 501)
            self.assertEqual(self.request('POST', '/api/check',
                {'name':'a', 'detector':'AK02', 'scenario_id':'gamma'})[0], 400)
            self.request()  # Its separate download cookie never grants catalog access.
            browser = {'X-Control-Token':'', 'Cookie':self.server.download_cookie+'='+self.server.download_token,
                       'Sec-Fetch-Site':'same-origin'}
            self.assertEqual(self.request(route='/api/scenarios', headers=browser)[0], 403)
        provider.assert_not_called()
        self.assertEqual(self.controller.calls, [])

    def test_scenario_failure_is_uniform_sanitized_and_has_no_partial_catalog(self):
        for error in (ValueError('C:/private/model/path'), OSError('secret input'), RuntimeError('raw failure')):
            with patch.object(U, 'checked_scenarios', side_effect=error):
                code, data, headers = self.request(route='/api/scenarios')
            self.assertEqual(code, 503)
            self.assertEqual(json.loads(data), {'error':'Scenario configuration preview is unavailable'})
            self.assertEqual(headers['Cache-Control'], 'no-store')
        self.assertEqual(self.controller.calls, [])

    def test_structured_input_and_size_refusal(self):
        for data in ({'name':'a','detector':'AK02','command':'echo'}, {'name':9,'detector':'AK02'}, ['a'], None):
            body = 'null' if data is None else json.dumps(data)
            self.assertEqual(self.request('POST','/api/check',body)[0], 400)
        self.assertEqual(self.request('POST','/api/check','x'*4097)[0], 400)
        self.assertEqual(self.request('POST','/api/check','{bad')[0], 400)
        self.assertEqual(self.request('POST','/api/check','{}',{'Content-Type':'text/plain'})[0], 400)
        self.assertEqual(self.controller.calls, [])
        self.assertEqual(self.request('POST','/api/check',{'name':'a','detector':'SAP22'})[0], 200)
        self.assertEqual(self.controller.calls, [{'name':'a','detector':'SAP22'}])

    def completed_fixture(self):
        folder = U.guarded(self.controller.root, U.BASE+'/own')
        folder.mkdir(parents=True)
        body = b'{"complete":true}\n'
        (folder/'run.json').write_bytes(body)
        complete = {'manifest_sha256':'unused', 'artifacts': {'run.json':{'sha256':hashlib.sha256(body).hexdigest(),'bytes':len(body)}}}
        complete_bytes = json.dumps(complete).encode()
        (folder/'COMPLETE.json').write_bytes(complete_bytes)
        self.controller.jobs = [{'name':'own','status':'completed','complete_sha256':hashlib.sha256(complete_bytes).hexdigest()}]
        return folder, body

    def test_owned_allowlist_and_exact_byte_download(self):
        folder, body = self.completed_fixture()
        code, data, headers = self.request(route='/api/file?name=own&file=run.json')
        self.assertEqual((code,data),(200,body)); self.assertIn('attachment',headers['Content-Disposition'])
        for route in ('/api/file?name=other&file=run.json', '/api/file?name=own&file=../../secret',
                      '/api/file?name=own&file=run.json&file=manifest.json','/api/file?name=own&file=inputs/0'):
            self.assertEqual(self.request(route=route)[0], 400)

    def test_changed_artifacts_and_receipts_refuse_download(self):
        folder, body = self.completed_fixture()
        (folder/'run.json').write_bytes(body+b'changed')
        self.assertEqual(self.request(route='/api/file?name=own&file=run.json')[0], 400)
        (folder/'run.json').write_bytes(body)
        (folder/'COMPLETE.json').write_bytes(b'{}')
        self.assertEqual(self.request(route='/api/file?name=own&file=run.json')[0], 400)

    def test_read_only_cookie_attachment_and_rotation(self):
        folder, body = self.completed_fixture()
        code, _, headers = self.request()
        self.assertEqual(code, 200)
        cookie = headers['Set-Cookie']
        self.assertIn('Path=/api/file; HttpOnly; SameSite=Strict', cookie)
        browser = {'X-Control-Token':'', 'Cookie':cookie.split(';')[0], 'Sec-Fetch-Site':'same-origin'}
        route = '/api/file?name=own&file=run.json'
        code, data, headers = self.request(route=route, headers=browser)
        self.assertEqual((code,data),(200,body))
        self.assertEqual(headers['Content-Disposition'], 'attachment; filename="own-run.json"')
        # A download capability never authorizes state or control.
        self.assertEqual(self.request(headers=browser)[0], 403)
        self.assertEqual(self.request('POST','/api/check',{'name':'a','detector':'AK02'},browser)[0], 403)
        self.assertEqual(self.controller.calls, [])
        for changes in ({'Cookie':''}, {'Cookie':'unrelated=wrong'}, {'Sec-Fetch-Site':''},
                        {'Sec-Fetch-Site':'same-site'}, {'Sec-Fetch-Site':'cross-site'},
                        {'Origin':'http://127.0.0.1:1'}, {'Host':'evil.example'}):
            self.assertEqual(self.request(route=route,headers={**browser,**changes})[0],403)
        self.server.download_token = 'rotated-session'
        self.assertEqual(self.request(route=route,headers=browser)[0],403)
        self.assertEqual(self.request(route=route)[0],200)
        self.assertNotIn('Set-Cookie', self.request(headers={'X-Control-Token':''})[2])

    def test_path_and_single_server_lease(self):
        for path in ('../a','/absolute','C:/private','a/../b','a//b'):
            with self.assertRaises(ValueError): U.guarded(self.controller.root,path)
        with U.server_lease(self.controller.root):
            with self.assertRaises((RuntimeError, OSError)):
                with U.server_lease(self.controller.root): pass
        # Released file remains evidence; a subsequent process can acquire it.
        with U.server_lease(self.controller.root): pass


if __name__ == '__main__': unittest.main()
