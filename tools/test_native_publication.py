"""Publication-only tests; no native transport, field solves or new radiation."""
import io, json, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
import native_publication as n
import build_site as b
from check_site import validate, MANIFEST

def archive(overrides=None, extra=None):
    files = {name: b'{}\n' if name.endswith(('.json','.jsonl')) else b'original\n'
             for name in n.ARCHIVE_NAMES-{'run.json'}}
    files.update(overrides or {})
    files['run.json'] = n.json_bytes({'artifacts': {k:n.sha(v) for k,v in files.items()}})
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as z:
        for name, data in files.items(): z.writestr(name, data)
        if extra: z.writestr(*extra)
    return buf.getvalue(), files

class PublicationTests(unittest.TestCase):
    def test_saved_trace_link_quote_styles(self):
        for quote in (chr(34),chr(39)):
            text='<h1>Saved trace</h1>'+''.join('<a href='+quote+n+quote+'>data</a>' for n in ('endpoints.csv','truth.jsonl','native-failures.jsonl'))
            adapted=n.adapt_trace_page(text,'<aside>scope</aside>')
            self.assertEqual(adapted.count('ledgers.zip'),3)
            self.assertTrue(adapted.startswith('<aside>scope</aside>'))
        with self.assertRaisesRegex(ValueError,'trace page link'):
            n.adapt_trace_page('<h1>Incomplete</h1>','scope')
    def test_live_native_ledgers_missing_or_corrupt(self):
        import sys
        from check_site import verify_live
        from urllib.parse import unquote, urlsplit
        names=['index.html','examples/cs137-10k/AK02/response/ledgers.zip','examples/cs137-10k/SAP22/response/ledgers.zip']
        files={name:b'fixture' for name in names}
        report={'build_id':'test','files':[{'path':name,'bytes':len(body),'sha256':n.sha(body)} for name,body in files.items()]}
        files[MANIFEST]=n.json_bytes(report)
        for mode in ('ok','missing','corrupt'):
            requested=set()
            def fake_open(request, timeout):
                name=unquote(urlsplit(request.full_url).path).removeprefix('/site/'); requested.add(name)
                if name.endswith('ledgers.zip') and mode=='missing': raise OSError('missing remote ledger')
                return io.BytesIO(b'corrupt' if name.endswith('ledgers.zip') and mode=='corrupt' else files[name])
            with patch.dict(sys.modules,{'ssl':object()}),patch('urllib.request.urlopen',fake_open):
                if mode=='ok':
                    verify_live('https://example.org/site/',report)
                    self.assertTrue(set(names)<=requested)
                else:
                    with self.assertRaises((ValueError,OSError)): verify_live('https://example.org/site/',report)
    def test_native_receipt_crlf_is_not_rewritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); native=root/'examples/cs137-10k/run.json'; native.parent.mkdir(parents=True)
            native.write_bytes(b'{\r\n  \"original\": true\r\n}\r\n')
            legacy=root/'legacy.json'; legacy.write_bytes(b'{}\r\n')
            before=native.read_bytes(); b.normalize_text_outputs(root)
            self.assertEqual(native.read_bytes(),before)
            self.assertEqual(legacy.read_bytes(),b'{}\n')
    def test_lossless_fixed_inventory(self):
        data, files = archive({'scalars.csv': b'0,-0.000000000000004,\"native_transport_failed\"\r\n'})
        self.assertEqual(n.validate_ledger_archive(data), {k:n.sha(v) for k,v in files.items()})
    def test_archive_traversal_rejected(self):
        with self.assertRaisesRegex(ValueError, 'inventory'):
            n.validate_ledger_archive(archive(extra=('../escape.csv',b'x'))[0])
    def test_rehashed_private_metadata_rejected(self):
        with self.assertRaisesRegex(ValueError, 'Private metadata'):
            n.validate_ledger_archive(archive({'truth.csv':b'C:/Users/private/data'})[0])
    def test_tampered_ledger_rejected(self):
        data, files = archive(); files['truth.csv'] = b'changed'
        out = io.BytesIO()
        with zipfile.ZipFile(out, 'w') as z:
            for name, content in files.items(): z.writestr(name, content)
        with self.assertRaisesRegex(ValueError, 'receipt mismatch'):
            n.validate_ledger_archive(out.getvalue())
    def test_snapshot_overlay_preserves_history(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); src=root/'docs'; out=root/'staging'; src.mkdir()
            for name in ('index.html','detectors/AK02/index.html','detectors/SAP22/index.html'):
                f=src/name; f.parent.mkdir(parents=True,exist_ok=True)
                f.write_text('<main><p>Original numeric evidence 0.12345678901234567</p></main>')
            (src/'historical.csv').write_bytes(b'original,-0.000001\r\n')
            (src/MANIFEST).write_bytes(n.json_bytes(validate(src,require_manifest=False)))
            old={f.relative_to(src):f.read_bytes() for f in src.rglob('*') if f.is_file()}
            def stub(campaign, target):
                target.mkdir(parents=True); (target/'comparison.html').write_text('saved result')
            with patch.object(b,'DESTINATION',src), patch.object(b,'OUT',out), patch.object(n,'assemble',stub):
                b.build_campaign_export(root/'unused')
            for name, data in old.items(): self.assertEqual((src/name).read_bytes(),data)
            self.assertEqual((out/'historical.csv').read_bytes(),old[Path('historical.csv')])
            for name in ('index.html','detectors/AK02/index.html','detectors/SAP22/index.html'):
                self.assertEqual((out/name).read_text().count('id="native-cs137-10k"'),1)
                self.assertIn('0.12345678901234567',(out/name).read_text())

if __name__ == '__main__': unittest.main()
