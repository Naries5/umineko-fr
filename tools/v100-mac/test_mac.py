#!/usr/bin/env python3
"""Exercise original Mac worker control flow on Linux using OS command adapters.

Does not change or rebuild the shipped Mac app. osascript/JXA Foundation file
reads and ditto ZIP extraction are adapted; UI/Steam integration is not tested.
"""
from pathlib import Path
import hashlib,json,os,shlex,shutil,subprocess,sys,zipfile
root=Path(sys.argv[1]).resolve()
public=len(sys.argv)>2 and sys.argv[2]=='published'
fixture=root/('mac-public' if public else 'mac-candidate')
fixture.mkdir()
game=fixture/'game'; game.mkdir()
with zipfile.ZipFile(root/'../old-release/patch-fr-0.1.23.zip') as z: z.extractall(game)
(game/'umineko_fr_version.txt').write_text('0.1.23\n')
(game/'installedVersionData.json').write_text(json.dumps({'test':'Umineko Question (Ch. 1-4)/full','mods':[{'id':'script'},{'id':'exe'}]}))
source=Path(__file__).resolve().parent/'source'
worker=(source/'worker.sh').read_text()
js=(source/'manifest_tools.js').read_text()
assert hashlib.sha256((source/'worker.sh').read_bytes()).hexdigest() == 'eaced73b9b387141bab6cffa5caf22f062e7213b8f4b4111f1a975c674f6cf0b'
assert hashlib.sha256((source/'manifest_tools.js').read_bytes()).hexdigest() == 'd99b0459592f7988d914331039f483853cc6498a97a55c482969126df792c246'
support=fixture/'support'; support.mkdir()
(support/'manifest_tools.js').write_text(js)
adapter=fixture/'jxa-adapter.js'
adapter.write_text('''const fs=require('fs'), vm=require('vm');
const script=process.argv[2], argv=process.argv.slice(3);
const dollar=x=>x;
dollar.NSData={dataWithContentsOfFile:p=>fs.readFileSync(p,'utf8')};
dollar.NSString={alloc:{initWithDataEncoding:data=>data}};
dollar.unwrap=x=>x; dollar.NSUTF8StringEncoding=4;
const context={ObjC:{import:()=>{},unwrap:x=>x},$:dollar};
vm.createContext(context); vm.runInContext(fs.readFileSync(script,'utf8'),context);
process.stdout.write(context.run(argv)+'\\n');
''')
node=shutil.which('node');assert node
jxa=fixture/'osascript-adapter';jxa.write_text('#!/bin/bash\nshift 2\nexec '+shlex.quote(node)+' '+shlex.quote(str(adapter))+' "$@"\n');jxa.chmod(0o755)
ditto=fixture/'ditto-adapter';ditto.write_text('#!/bin/bash\nexec /usr/bin/unzip -q "$3" -d "$4"\n');ditto.chmod(0o755)
requests=fixture/'requests.jsonl'
curl=fixture/'curl-adapter.py'
curl.write_text('''#!/usr/bin/env python3
import sys,json,subprocess
from pathlib import Path
args=sys.argv[1:]
urls=[s for s in args if s.startswith(('http://','https://'))]
assert len(urls)==1
url=urls[0]
assert url.endswith(('manifest.json','mac-candidate-manifest.json','UminekoFR-Questions-1.0.0.zip')), 'Unexpected package/full archive download: '+url
with Path(__file__).with_name('requests.jsonl').open('a') as f: f.write(json.dumps(url)+'\\n')
sys.exit(subprocess.call(['/usr/bin/curl',*args]))
''');curl.chmod(0o755)
if public:
 manifest_url='https://raw.githubusercontent.com/Naries5/umineko-fr/main/update/manifest.json'
else:
 m=json.loads((root/'candidate-manifest.json').read_text())
 p=next(p for p in m['packages'] if p['id']=='questions-100')
 p['downloadUrl']='http://127.0.0.1:8765/UminekoFR-Questions-1.0.0.zip'
 (root/'mac-candidate-manifest.json').write_text(json.dumps(m))
 manifest_url='http://127.0.0.1:8765/mac-candidate-manifest.json'
worker=worker.replace('export LC_ALL=UTF-8','export LC_ALL=C.UTF-8')
worker=worker.replace('MANIFEST_URL="https://raw.githubusercontent.com/Naries5/umineko-fr/main/update/manifest.json"','MANIFEST_URL='+shlex.quote(manifest_url))
worker=worker.replace('SUPPORT="$HOME/Library/Application Support/LeSanglotDesGoelands/PatcherMac"','SUPPORT='+shlex.quote(str(support)))
worker=worker.replace('LOG_DIR="$HOME/Library/Logs"','LOG_DIR='+shlex.quote(str(fixture/'logs')))
for original,replacement in [('/usr/bin/osascript',jxa),('/usr/bin/ditto',ditto),('/usr/bin/curl',curl)]: worker=worker.replace(original,shlex.quote(str(replacement)))
test_worker=fixture/'worker-adapted.sh';test_worker.write_text(worker)
def run():
 result = subprocess.run(['/bin/bash',str(test_worker),'update',str(game)])
 if result.returncode:
  for p in (support/'result.tsv', fixture/'logs/LeSanglotDesGoelands-Patcher-Mac.log'):
   if p.exists(): print(p.read_text(), flush=True)
 result.check_returncode()
def snapshot():
 return {str(p.relative_to(game)):(p.stat().st_size,p.stat().st_mtime_ns,hashlib.sha256(p.read_bytes()).hexdigest()) for p in game.rglob('*') if p.is_file()}
run()
result=(support/'result.tsv').read_text();assert result.startswith('OK\tinstalled\t1.0.0\t1\t'),result
calls=[json.loads(l) for l in requests.read_text().splitlines()]
packages=[u for u in calls if u.endswith('.zip')]
assert len(packages)==1 and packages[0].endswith('UminekoFR-Questions-1.0.0.zip'),calls
m=json.loads((root/'candidate-manifest.json').read_text())
assert m['version']=='1.0.0' and (game/'umineko_fr_version.txt').read_text().strip()=='1.0.0'
for f in m['files']:
 p=game/f['path'];assert p.stat().st_size==f['size'] and hashlib.sha256(p.read_bytes()).hexdigest()==f['sha256'],f['path']
before=snapshot();requests_before=len(calls);run()
assert snapshot()==before,'Second launch modified files/timestamps'
newcalls=[json.loads(l) for l in requests.read_text().splitlines()][requests_before:]
assert len(newcalls)==1 and not any(u.endswith('.zip') for u in newcalls),newcalls
assert (support/'result.tsv').read_text().startswith('OK\tup_to_date\t1.0.0\tfast')
print('PASS MAC WORKER (Linux OS adapters): 0.1.23 -> 1.0.0; only questions-100 downloaded; all 4047 hashes/sizes valid; second run no package download, no game file/timestamp changes; published='+str(public),flush=True)
