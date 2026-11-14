#!/usr/bin/env python3
"""Finalize the already verified release immediately, as explicitly authorized."""
import base64,copy,hashlib,json,os,subprocess,time,urllib.request,zipfile
from pathlib import Path
REPO='Naries5/umineko-fr'
RID=445145996
WAIT_RUN=43576241822
EXPECTED={
 'UminekoFR-Questions-1.0.0.zip':(4688645,'bccc71a782bc8571364cb54e0e243eed13c209284e5bc7c66ff358ccd3534447'),
 'patch-fr-1.0.0.zip':(1102353278,'a6a5664473d2c742179f68283821dada5a0d365822269f70c7ddbe664839814a')}
def api(path,payload=None,method='GET'):
 args=['gh','api','repos/'+REPO+'/'+path,'--method',method]
 if payload is not None: args+=['--input','-']
 p=subprocess.run(args,input=json.dumps(payload) if payload is not None else None,text=True,capture_output=True,check=True)
 return json.loads(p.stdout) if p.stdout.strip() else None
def sha(p):
 with open(p,'rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def content(path):
 r=api('contents/'+path+'?ref=main')
 return r,json.loads(base64.b64decode(r['content']))
proof=json.loads(Path('.staging/v1.0.0/validation-report.json').read_text())
assert proof['releaseId']==RID and proof['status']=='draft-verified'
assert {a['name']:(a['size'],a['sha256']) for a in proof['assets']}==EXPECTED
old=api('actions/runs/'+str(WAIT_RUN))
if old['status']!='completed':
 api('actions/runs/'+str(WAIT_RUN)+'/cancel',{},'POST')
 for _ in range(60):
  old=api('actions/runs/'+str(WAIT_RUN))
  if old['status']=='completed':break
  time.sleep(2)
assert old['status']=='completed' and old['conclusion']=='cancelled',old
print('Old waiting workflow conclusively cancelled',flush=True)
releases=api('releases?per_page=100')
matches=[r for r in releases if r['tag_name']=='v1.0.0']
assert len(matches)==1 and matches[0]['id']==RID
r=api('releases/'+str(RID))
assets={a['name']:a for a in r['assets']}
assert set(assets)==set(EXPECTED)
for name,(size,digest) in EXPECTED.items():
 a=assets[name];assert a['state']=='uploaded' and a['size']==size and a['digest']=='sha256:'+digest
assert not r['prerelease']
if r['draft']:
 r=api('releases/'+str(RID),{'draft':False,'make_latest':'true'},'PATCH')
assert not r['draft'] and api('releases/tags/v1.0.0')['id']==RID
out=Path('publish');out.mkdir(exist_ok=True)
for name,(size,digest) in EXPECTED.items():
 url='https://github.com/'+REPO+'/releases/download/v1.0.0/'+name
 p=out/name
 subprocess.run(['curl','--fail','--location','--retry','3','--silent','--show-error','--output',str(p),url],check=True)
 assert p.stat().st_size==size and sha(p)==digest
 print('PUBLIC ANONYMOUS DOWNLOAD VERIFIED',name,size,digest,flush=True)
with zipfile.ZipFile(out/'UminekoFR-Questions-1.0.0.zip') as z:
 assert z.namelist()==['0.u'] and z.testzip() is None
 script=z.read('0.u')
assert len(script)==18024811 and hashlib.sha256(script).hexdigest()=='001f81c43ff5c60168ee857013b38dce3b72046395ff072e8f84ce85f9759235'
current,baseline=content('update/manifest.json')
assert baseline['version']=='0.1.23' and baseline==json.loads(Path('update/manifest.json').read_text())
new=copy.deepcopy(baseline)
new.update(version='1.0.0',downloadUrl='https://github.com/'+REPO+'/releases/download/v1.0.0/patch-fr-1.0.0.zip',sha256=EXPECTED['patch-fr-1.0.0.zip'][1],notes='Première sortie officielle : traduction française intégrale de l’arc Questions (épisodes 1 à 4).')
package={'id':'questions-100','downloadUrl':'https://github.com/'+REPO+'/releases/download/v1.0.0/UminekoFR-Questions-1.0.0.zip','sha256':EXPECTED['UminekoFR-Questions-1.0.0.zip'][1],'size':4688645}
assert not any(p['id']==package['id'] for p in new['packages'])
new['packages'].append(package)
for f in new['files']:
 if f['path']=='0.u':f.update(sha256=hashlib.sha256(script).hexdigest(),size=len(script),packageId=package['id'])
assert len(new['files'])==4047 and len(new['packages'])==23 and new['updater']==baseline['updater']
assert [(a,b) for a,b in zip(baseline['files'],new['files']) if a!=b]==[(next(f for f in baseline['files'] if f['path']=='0.u'),next(f for f in new['files'] if f['path']=='0.u'))]
assert new['packages'][:-1]==baseline['packages'] and not new.get('deletePaths')
with zipfile.ZipFile(out/'patch-fr-1.0.0.zip') as z:
 names=[i.filename for i in z.infolist() if not i.is_dir()]
 assert len(names)==len(set(names))==4047 and set(names)=={f['path'] for f in new['files']}
 for f in new['files']:
  with z.open(f['path']) as stream: h=hashlib.file_digest(stream,'sha256').hexdigest()
  assert h==f['sha256'] and z.getinfo(f['path']).file_size==f['size'],f['path']
print('Public full archive verified against all 4047 entries; 4046 unchanged',flush=True)
(out/'candidate-manifest.json').write_text(json.dumps(new,ensure_ascii=False))
raw=json.dumps(new,ensure_ascii=False,separators=(',',':')).encode()
api('contents/update/manifest.json',{'message':'release: activate publicly verified v1.0.0 immediately as authorized','content':base64.b64encode(raw).decode(),'sha':current['sha'],'branch':'main'},'PUT')
assert content('update/manifest.json')[1]==new
subprocess.run(['curl','--fail','--location','--silent','--show-error','-H','Cache-Control: no-cache','--output',str(out/'public-manifest.json'),'https://raw.githubusercontent.com/'+REPO+'/main/update/manifest.json'],check=True)
assert json.loads((out/'public-manifest.json').read_text())==new
print('PUBLIC MANIFEST VERIFIED: version 1.0.0, schema 3, 4047 files, 23 packages',flush=True)
subprocess.run(['gh','release','download','v0.1.23','--repo',REPO,'--pattern','patch-fr-0.1.23.zip','--dir','old-release'],check=True)
subprocess.run(['dotnet','run','--project','tools/v100-compat/Compat.csproj','--configuration','Release','--','publish','published'],check=True)
subprocess.run(['python3','tools/v100-mac/test_mac.py','publish','published'],check=True)
old=api('actions/runs/'+str(WAIT_RUN));assert old['status']=='completed' and old['conclusion']=='cancelled'
proof.update(status='published-and-tested',activeManifestVersion='1.0.0',releaseUrl=r['html_url'],workflowUrl='https://github.com/'+REPO+'/actions/runs/'+os.environ['GITHUB_RUN_ID'],waitingWorkflowConclusion='cancelled',publicationTiming='immediate; explicitly authorized by owner')
path='.staging/v1.0.0/validation-report.json'
prior=api('contents/'+path+'?ref=main')
api('contents/'+path,{'message':'release: record immediate v1.0.0 publication and public compatibility checks','content':base64.b64encode(json.dumps(proof,ensure_ascii=False,indent=2).encode()).decode(),'sha':prior['sha'],'branch':'main'},'PUT')
print('SUCCESS: v1.0.0 public, manifest active, public updater checks passed, old wait cancelled',flush=True)
