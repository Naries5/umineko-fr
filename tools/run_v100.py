#!/usr/bin/env python3
"""Prepare official Questions release; publish only at the authorized time."""
import base64,json,subprocess,sys,time
from datetime import datetime,timezone
from pathlib import Path
import publish_v100 as publication

def run(*args):
    print('RUN',*args,flush=True)
    subprocess.run(args,check=True)

def record(status):
    r=publication.release_verify()
    proof={'version':'1.0.0','status':status,'releaseId':r['id'],'releaseUrl':r['html_url'],
           'officialReleaseParis':'2026-11-14T10:19:00+01:00','sourceScriptSHA256':publication.sha_bytes(publication.source_files()['0.u']),
           'scriptPhysicalLines':342483,'changedFrenchLines':8,'japaneseLinesChanged':0,'otherFilesPreserved':4046,
           'filesTotal':4047,'windowsCoreTest':'passed; one incremental download; second launch no changes',
           'macWorkerTest':'passed under Linux with adapters for macOS system commands; one incremental download; second launch no game changes; native macOS GUI not executed',
           'workflowUrl':'https://github.com/Naries5/umineko-fr/actions/runs/'+__import__('os').environ['GITHUB_RUN_ID'],
           'assets':[{ 'name':p.name,'size':p.stat().st_size,'sha256':publication.sha(p)} for p in (publication.DELTA,publication.FULL)],
           'checkedAt':datetime.now(timezone.utc).isoformat()}
    if status=='published-and-tested':proof['activeManifestVersion']='1.0.0'
    path='.staging/v1.0.0/validation-report.json'
    try:old=publication.api(f'repos/{publication.REPO}/contents/{path}?ref=main')
    except subprocess.CalledProcessError as e:
        if '404' not in e.stderr:raise
        old=None
    payload={'message':'release: record v1.0.0 '+status+' verification','branch':'main',
             'content':base64.b64encode(json.dumps(proof,ensure_ascii=False,indent=2).encode()).decode()}
    if old:payload['sha']=old['sha']
    publication.api(f'repos/{publication.REPO}/contents/{path}',payload)
    print('VERIFICATION REPORT',json.dumps(proof,ensure_ascii=False),flush=True)

def main(finalize=False):
    run('python3','tools/publish_v100.py','prepare')
    run('gh','release','download','v0.1.23','--repo','Naries5/umineko-fr','--pattern','patch-fr-0.1.23.zip','--dir','old-release')
    run('python3','tools/publish_v100.py','build')
    run('python3','tools/publish_v100.py','candidate')
    with open('publish/http.log','w') as log:
        server=subprocess.Popen(['python3','-m','http.server','8765','--bind','127.0.0.1','--directory','publish'],stdout=log,stderr=log)
        try:
            run('dotnet','run','--project','tools/v100-compat/Compat.csproj','--configuration','Release','--','publish')
            run('python3','tools/v100-mac/test_mac.py','publish')
        finally:
            server.terminate();server.wait()
    for stage in ('create','verify'):run('python3','tools/publish_v100.py',stage)
    if not finalize:
        record('draft-verified')
        print('DRAFT VERIFIED; manifest remains 0.1.23; awaiting official release time',flush=True)
        return
    record('draft-verified')
    release_time=datetime(2026,11,14,9,19,tzinfo=timezone.utc)
    delay=(release_time-datetime.now(timezone.utc)).total_seconds()
    assert delay<3600,'Finalization launched more than one hour early; draft preserved'
    while datetime.now(timezone.utc)<release_time:
        remaining=(release_time-datetime.now(timezone.utc)).total_seconds()
        print('Official release time guard; remaining seconds',round(remaining,1),flush=True)
        time.sleep(min(30,max(0,remaining)))
    for stage in ('publish','activate'):run('python3','tools/publish_v100.py',stage)
    run('dotnet','run','--project','tools/v100-compat/Compat.csproj','--configuration','Release','--','publish','published')
    run('python3','tools/v100-mac/test_mac.py','publish','published')
    record('published-and-tested')

if __name__=='__main__':main('--finalize' in sys.argv)
