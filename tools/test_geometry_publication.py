import hashlib, io, json, sys, unittest, zipfile
from unittest.mock import patch
from geometry_publication import archive_contents, ORIGINALS
from check_site import MANIFEST, verify_live
class GeometryPublicationTests(unittest.TestCase):
    def archive(self, change=None, duplicate=False, symlink=False):
        b=io.BytesIO()
        with zipfile.ZipFile(b,'w',zipfile.ZIP_DEFLATED) as z:
            for name in (*ORIGINALS,'cryostat-source.json'):
                value=b'{}' if name.endswith('.json') else b'plain text'
                if change and name==change[0]: value=change[1]
                item=zipfile.ZipInfo(name)
                if symlink and name=='run.mac': item.external_attr=0o120777 << 16
                z.writestr(item,value)
            if duplicate: z.writestr('run.mac',b'extra')
        return b.getvalue()
    def test_fixed_archive(self):
        self.assertEqual(set(archive_contents(self.archive())),set(ORIGINALS)|{'cryostat-source.json'})
    def test_duplicate(self):
        with self.assertRaisesRegex(ValueError,'inventory'): archive_contents(self.archive(duplicate=True))
    def test_symlink(self):
        with self.assertRaisesRegex(ValueError,'Unsafe'): archive_contents(self.archive(symlink=True))
    def test_private_metadata(self):
        with self.assertRaisesRegex(ValueError,'Private'): archive_contents(self.archive(('run.json',b'{"path":"C:/Users/test/input"}')))
    def test_all_geometry_files_verified_online(self):
        from urllib.parse import unquote,urlsplit
        base='examples/cs137-10k-geometry/'
        files={base+'geometry.html':b'<html/>',base+'AK02/originals.zip':b'zip',base+'AK02/events-09900.json':b'{}'}
        report={'build_id':'synthetic','files':[{'path':n,'bytes':len(b),'sha256':hashlib.sha256(b).hexdigest()} for n,b in files.items()]}
        files[MANIFEST]=json.dumps(report).encode(); requested=set()
        def download(request,timeout):
            name=unquote(urlsplit(request.full_url).path).removeprefix('/site/')
            requested.add(name)
            if name not in files: raise FileNotFoundError(name)
            return io.BytesIO(files[name])
        with patch.dict(sys.modules,{'ssl':object()}),patch('urllib.request.urlopen',download):
            verify_live('https://example.org/site/',report)
            self.assertTrue(set(files)<=requested)
            files[base+'AK02/originals.zip']=b'bad'
            with self.assertRaisesRegex(ValueError,'differs'): verify_live('https://example.org/site/',report)
            del files[base+'AK02/originals.zip']
            with self.assertRaises(FileNotFoundError): verify_live('https://example.org/site/',report)
if __name__=='__main__': unittest.main(verbosity=2)
