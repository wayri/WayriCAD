"""Packaging regressions for the v0.7.1 PCM distribution; no KiCad host mocked as real."""
from pathlib import Path
import hashlib
import json
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import build_pcm as b
import validate_pcm as v

class PCMPackageTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.tmp=tempfile.TemporaryDirectory(prefix='wayricad-pcm-tests-');cls.base=Path(cls.tmp.name)
  cls.source=cls.base/'source';cls.source.mkdir()
  fixed=['plugin.json','desktop_entrypoint.py','entrypoint.py','cli.py','requirements.txt','tools/pcm-package.json',
         'bomstudio/__init__.py','bomstudio/server.py','bomstudio/engine.py','web/index.html','web/app.js','resources/ICON_LICENSE.md']
  fixed += [str(p.relative_to(ROOT)) for p in (ROOT/'resources').glob('icon*.png')]
  for rel in fixed:
   dest=cls.source/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/rel,dest)
  cls.payload=b.collect(cls.source)
 @classmethod
 def tearDownClass(cls):cls.tmp.cleanup()
 def archive(self,payload=None,extra=None):
  path=self.base/(self.id().split('.')[-1]+'.zip')
  with zipfile.ZipFile(path,'w',compression=zipfile.ZIP_DEFLATED) as z:
   for name,data in (payload if payload is not None else self.payload).items():z.writestr(name,data)
   if extra:
    for name,data in extra:z.writestr(name,data)
  return path
 def changed(self,filename,op):
  payload=dict(self.payload);obj=json.loads(payload[filename]);op(obj);payload[filename]=json.dumps(obj).encode();return payload
 def assert_invalid(self,payload,pattern):
  with self.assertRaisesRegex(v.PackageError,pattern):v.validate(self.archive(payload))
 def test_valid_flat_package(self):
  r=v.validate(self.archive());self.assertEqual(r['version'],'3.1.0');self.assertFalse(r['host_installation_tested']);self.assertEqual(r['installed_plugin_relative_path'],'plugins/com_github_wayri_wayricad_bom-studio/plugin.json')
 def test_root_metadata_required(self):
  p=dict(self.payload);p.pop('metadata.json');self.assert_invalid(p,'Missing metadata.json')
 def test_old_wrapper_rejected(self):self.assert_invalid({'outer/'+k:d for k,d in self.payload.items()},'Unexpected archive wrapper')
 def test_legacy_swig_runtime_rejected(self):self.assert_invalid(self.changed('metadata.json',lambda x:x['versions'][0].update(runtime='swig')),'runtime must explicitly be ipc')
 def test_implicit_runtime_rejected(self):self.assert_invalid(self.changed('metadata.json',lambda x:x['versions'][0].pop('runtime')),'runtime must explicitly be ipc')
 def test_two_versions_rejected(self):self.assert_invalid(self.changed('metadata.json',lambda x:x['versions'].append(dict(x['versions'][0]))),'exactly one version')
 def test_repository_hash_inside_package_rejected(self):self.assert_invalid(self.changed('metadata.json',lambda x:x['versions'][0].update(download_sha256='a'*64)),'repository-only')
 def test_identifier_mismatch_rejected(self):self.assert_invalid(self.changed('plugins/plugin.json',lambda x:x.update(identifier='wrong.plugin')),'identifiers disagree')
 def test_missing_action_script_rejected(self):self.assert_invalid(self.changed('plugins/plugin.json',lambda x:x['actions'][0].update(entrypoint='missing.py')),'entrypoint missing')
 def test_dark_array_required(self):self.assert_invalid(self.changed('plugins/plugin.json',lambda x:x['actions'][0].pop('icons-dark')),'Missing dark')
 def test_wrong_size_icon_rejected(self):
  p=dict(self.payload);p['plugins/resources/icon-24.png']=p['plugins/resources/icon-64.png'];self.assert_invalid(p,'dimensions must be 24')
 def test_fake_png_rejected(self):
  p=dict(self.payload);p['resources/icon.png']=b'not a PNG';self.assert_invalid(p,'not a PNG')
 def test_broken_png_crc_rejected(self):
  p=dict(self.payload);data=bytearray(p['resources/icon.png']);data[-1]^=1;p['resources/icon.png']=bytes(data);self.assert_invalid(p,'CRC mismatch')
 def test_duplicate_json_keys_rejected(self):
  p=dict(self.payload);p['metadata.json']=b'{"name":"A","name":"B"}';self.assert_invalid(p,'duplicate JSON key')
 def test_manifest_tampering_rejected(self):
  p=dict(self.payload);p['plugins/web/app.js']+=b'\n// changed';self.assert_invalid(p,'Manifest integrity mismatch')
 def test_manifest_missing_member_rejected(self):
  p=dict(self.payload);p['plugins/unlisted.txt']=b'x';self.assert_invalid(p,'Manifest membership mismatch')
 def test_path_traversal_rejected(self):
  p=dict(self.payload);p['plugins/../outside.txt']=b'x';self.assert_invalid(p,'Unsafe ZIP path')
 def test_windows_absolute_path_rejected(self):
  p=dict(self.payload);p['C:/outside.txt']=b'x';self.assert_invalid(p,'Unsafe ZIP path')
 def test_case_collision_rejected(self):
  p=dict(self.payload);p['plugins/ENTRYPOINT.py']=b'x';self.assert_invalid(p,'case-colliding')
 def test_bytecode_rejected(self):
  p=dict(self.payload);p['plugins/__pycache__/bad.pyc']=b'x';self.assert_invalid(p,'bytecode')
 def test_symlink_rejected(self):
  i=zipfile.ZipInfo('plugins/link');i.create_system=3;i.external_attr=(stat.S_IFLNK|0o777)<<16
  with self.assertRaisesRegex(v.PackageError,'Symlinks'):v.validate(self.archive(extra=[(i,b'elsewhere')]))
 def test_duplicate_zip_member_rejected(self):
  import warnings
  with warnings.catch_warnings():
   warnings.simplefilter('ignore',UserWarning)
   path=self.archive(extra=[('metadata.json',self.payload['metadata.json'])])
  with self.assertRaisesRegex(v.PackageError,'Duplicate'):v.validate(path)
 def test_builder_refuses_existing_output(self):
  dest=self.base/'existing.zip';dest.write_bytes(b'original')
  with self.assertRaises(FileExistsError):b.build(self.source,dest)
  self.assertEqual(dest.read_bytes(),b'original')
 def test_builder_refuses_output_in_source(self):
  with self.assertRaisesRegex(v.PackageError,'outside'):b.build(self.source,self.source/'out.zip')
 def test_builder_deterministic(self):
  a=self.base/'det-a.zip';c=self.base/'det-b.zip';b.build(self.source,a);b.build(self.source,c);self.assertEqual(a.read_bytes(),c.read_bytes())
 def test_all_icon_rasters_valid(self):
  for size in (16,24,32,48,64,96,128):
   for prefix in ('icon-','icon-dark-'):self.assertEqual(v.png_info((ROOT/'resources'/f'{prefix}{size}.png').read_bytes(),size)['format'],'RGBA8')
 def test_icon_sources_exact_upstream(self):
  for file,expected in [('file_bom-light.svg','e21a016499995adf0221a8df05ef51a7d00ea239'),('file_bom-dark.svg','67d8ed722eca201dcf6c50c857c8c97191cdb007')]:
   data=(ROOT/'resources/sources'/file).read_bytes();self.assertEqual(hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest(),expected);self.assertIn(b'creativecommons.org/licenses/by-sa/4.0',data)
 def test_dark_artwork_differs(self):self.assertNotEqual((ROOT/'resources/icon-48.png').read_bytes(),(ROOT/'resources/icon-dark-48.png').read_bytes())
 def test_windows_launcher_flat_layout(self):
  s=(ROOT/'START_BOM_STUDIO_WINDOWS.bat').read_text();self.assertIn('%~dp0launch_windows.ps1',s);self.assertNotIn('%~dp0wayricad_bom_studio',s)
 def test_no_font_files(self):
  self.assertFalse(any(p.suffix.lower() in ('.ttf','.otf','.woff','.woff2') for p in ROOT.rglob('*')))
 def test_entrypoint_help_from_unrelated_working_directory(self):
  r=subprocess.run([sys.executable,str(ROOT/'entrypoint.py'),'--help'],cwd=self.base,capture_output=True,text=True,timeout=15)
  self.assertEqual(r.returncode,0,r.stderr);self.assertIn('--engineering-demo',r.stdout)
 def test_runtime_version_matches_metadata(self):
  sys.path.insert(0,str(ROOT));import bomstudio
  self.assertEqual(bomstudio.__version__,json.loads((ROOT/'tools/pcm-package.json').read_text())['versions'][0]['version'])

if __name__=='__main__':unittest.main()
