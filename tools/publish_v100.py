#!/usr/bin/env python3
"""Publish the supplied Questions script; preserve every other v0.1.23 file."""
import base64
import copy
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import zipfile

REPO = 'Naries5/umineko-fr'
TAG = 'v1.0.0'
SOURCE_SHA = 'bccc71a782bc8571364cb54e0e243eed13c209284e5bc7c66ff358ccd3534447'
RELEASE_STATE = Path('publish/release.json')
OLD_FULL_SHA = 'cdd7ae16cbf70604b9009f2d2c6e14c7c998701dc70869eeb33c23c7e78ccce3'
OUT = Path('publish')
DELTA = OUT / 'UminekoFR-Questions-1.0.0.zip'
FULL = OUT / 'patch-fr-1.0.0.zip'
SOURCE = OUT / 'source.zip'
OLD = Path('old-release/patch-fr-0.1.23.zip')
BASE = Path('update/manifest.json')

def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()

def sha(p):
    with open(p, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout

def api(endpoint, payload=None, method='PUT'):
    args = ['gh', 'api', endpoint]
    if payload is not None:
        args += ['--method', method, '--input', '-']
    p = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                       text=True, capture_output=True, check=True)
    return json.loads(p.stdout)

def source_files():
    assert sha(SOURCE) == SOURCE_SHA, 'Supplied ZIP changed'
    with zipfile.ZipFile(SOURCE) as z:
        assert z.namelist() == ['0.u'] and z.testzip() is None
        b = z.read('0.u')
        assert len(b) == 18024811
        assert sha_bytes(b) == '001f81c43ff5c60168ee857013b38dce3b72046395ff072e8f84ce85f9759235'
        b.decode('utf-8')
        return {'0.u': b}

def find_release():
    matches = []
    page = 1
    while True:
        batch = api(f'repos/{REPO}/releases?per_page=100&page={page}')
        matches.extend(r for r in batch if r['tag_name'] == TAG)
        if len(batch) < 100:
            break
        page += 1
    assert len(matches) <= 1, 'Duplicate release'
    if matches:
        r = matches[0]
        assert not r['prerelease']
        RELEASE_STATE.write_text(json.dumps({'id': r['id']}))
        return api(f'repos/{REPO}/releases/{r["id"]}')

def get_release():
    state = json.loads(RELEASE_STATE.read_text())
    r = api(f'repos/{REPO}/releases/{state["id"]}')
    assert r['id'] == state['id'] and r['tag_name'] == TAG and not r['prerelease']
    return r

def download_asset(a, destination):
    assert a['state'] == 'uploaded'
    with destination.open('xb') as output:
        subprocess.run(['gh','api',f'repos/{REPO}/releases/assets/{a["id"]}',
                        '-H','Accept: application/octet-stream'],stdout=output,check=True)
    assert destination.stat().st_size == a['size']
    assert a['digest'] == 'sha256:' + sha(destination)

def prepare():
    OUT.mkdir(exist_ok=True)
    parts = sorted(Path('.staging/v1.0.0/chunks').glob('*.part'))
    assert [p.name for p in parts] == [f'{i:03d}.part' for i in range(10)]
    with SOURCE.open('xb') as f:
        for p in parts:
            f.write(p.read_bytes())
    assert sha(SOURCE) == 'eee67f02c8e1380c5f2ebc35aac78d4b739dbe2ca0398cd9c3892d8f13985b0d'
    with zipfile.ZipFile(SOURCE) as z:
        assert z.namelist() == ['0.u'] and z.testzip() is None
        script = z.read('0.u')
    assert sha_bytes(script) == '001f81c43ff5c60168ee857013b38dce3b72046395ff072e8f84ce85f9759235'
    info = zipfile.ZipInfo('0.u', (2026,11,14,8,13,0))
    info.create_system = 3
    info.external_attr = 25165824
    with zipfile.ZipFile(SOURCE, 'w', compression=8, compresslevel=9) as z:
        z.writestr(info, script, compress_type=8, compresslevel=9)
    # Exact byte-for-byte reproduction of the attached ZIP, checked locally.
    assert SOURCE.stat().st_size == 4688645 and sha(SOURCE) == SOURCE_SHA
    files = source_files()
    m = json.loads(BASE.read_text())
    assert m['version'] == '0.1.23' and m['schemaVersion'] == 3
    assert m['sha256'] == OLD_FULL_SHA and not m.get('deletePaths')
    index = {f['path']: f for f in m['files']}
    assert len(index) == len(m['files']) == 4047
    for path in index:
        assert path == str(PurePosixPath(path)) and not PurePosixPath(path).is_absolute()
        assert '..' not in PurePosixPath(path).parts and '\\' not in path
    assert sha_bytes(files['0.u']) != index['0.u']['sha256']
    shutil.copyfile(BASE, OUT / 'baseline-manifest.json')
    shutil.copyfile(SOURCE, DELTA)
    r = find_release()
    if r:
        assert r['draft'], 'Release already public; stop without changing it'
        assets = {a['name']: a for a in r['assets']}
        assert len(r['assets']) == len(assets) == 2
        assert assets[DELTA.name]['digest'] == 'sha256:' + SOURCE_SHA
        download_asset(assets[FULL.name], FULL)
        print('Resuming existing draft by ID', r['id'], flush=True)
    print('Verified exact supplied ZIP: only 0.u changed', flush=True)

def build():
    files = source_files()
    assert sha(OLD) == OLD_FULL_SHA
    m = json.loads((OUT / 'baseline-manifest.json').read_text())
    expected = {f['path']: f for f in m['files']}
    with zipfile.ZipFile(OLD) as z:
        infos = z.infolist()
        assert len(z.namelist()) == len(set(z.namelist()))
        assert {i.filename for i in infos if not i.is_dir()} == set(expected)
        for i in infos:
            if not i.is_dir():
                with z.open(i) as f:
                    h = hashlib.file_digest(f, 'sha256').hexdigest()
                assert h == expected[i.filename]['sha256'], f'Old file differs: {i.filename}'
                assert i.file_size == expected[i.filename]['size']
    with zipfile.ZipFile(OLD) as z:
        old_script = z.read('0.u')
    new_script = files['0.u']
    old_lines, new_lines = old_script.splitlines(), new_script.splitlines()
    import difflib
    changes = [op for op in difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=True).get_opcodes()
               if op[0] != 'equal']
    print('SCRIPT COMPARISON:', json.dumps({
        'oldSize':len(old_script),'newSize':len(new_script),
        'oldSHA256':sha_bytes(old_script),'newSHA256':sha_bytes(new_script),
        'oldLines':len(old_lines),'newLines':len(new_lines),'changedRanges':changes}), flush=True)
    assert len(old_lines) == len(new_lines) == 342483
    changed = [(a,b) for a,b in zip(old_lines,new_lines) if a != b]
    assert len(changed) == 8, f'Expected 8 changed lines, got {len(changed)}'
    assert all(a.startswith(b'langen') and b.startswith(b'langen') for a,b in changed)
    assert all(a.split(b'^')[::2] == b.split(b'^')[::2] and a.count(b'^') == b.count(b'^') for a,b in changed), 'Script structure changed'
    assert [l for l in old_lines if l.startswith(b'langjp')] == [l for l in new_lines if l.startswith(b'langjp')], 'Japanese lines changed'
    if not FULL.exists():
        shutil.copyfile(OLD, FULL)
        work = OUT / 'replacement'
        work.mkdir()
        (work / '0.u').write_bytes(new_script)
        # Replace only this member; the final archive retains every original path.
        run('zip', '-q', '-d', str(FULL), '0.u')
        subprocess.run(['zip','-q','-6',str(FULL.resolve()),'0.u'], cwd=work, check=True)
    with zipfile.ZipFile(FULL) as z:
        assert len(z.namelist()) == len(set(z.namelist()))
        assert {i.filename for i in z.infolist() if not i.is_dir()} == set(expected)
        for n,entry in expected.items():
            with z.open(n) as f:
                h = hashlib.file_digest(f, 'sha256').hexdigest()
            target = sha_bytes(files[n]) if n in files else entry['sha256']
            assert h == target, f'Full archive mismatch: {n}'
            assert z.getinfo(n).file_size == (len(files[n]) if n in files else entry['size'])
    print('Full archive verified: 1 replacement, 4046 other files byte-identical, including all images and Answers; no deletions')
    for p in (DELTA,FULL):
        print(p.name, p.stat().st_size, sha(p))

def release_verify():
    r = get_release()
    assets = {a['name']: a for a in r['assets']}
    assert len(r['assets']) == len(assets) == 2
    assert set(assets) == {DELTA.name, FULL.name}
    for p in (DELTA, FULL):
        a = assets[p.name]
        assert a['state'] == 'uploaded' and a['size'] == p.stat().st_size
        assert a['digest'] == 'sha256:' + sha(p)
    return r

def create():
    r = find_release()
    if not r:
        run('gh','release','create',TAG,str(DELTA),str(FULL),'--repo',REPO,
            '--target',run('git','rev-parse','HEAD').strip(),'--draft',
            '--title','Le Sanglot des Goélands — Version 1.0.0 | Arc Questions',
            '--notes-file','tools/v100-release-notes.md')
        r = find_release()
    assert r and r['draft']
    release_verify()
    print('Draft ready, ID', r['id'], flush=True)

def verify():
    r = release_verify()
    d = OUT / 'remote-verified'
    d.mkdir(exist_ok=True)
    assets = {a['name']: a for a in r['assets']}
    for p in (DELTA, FULL):
        remote = d / p.name
        download_asset(assets[p.name], remote)
        assert sha(remote) == sha(p) and remote.stat().st_size == p.stat().st_size
        print('REMOTE VERIFIED', p.name, remote.stat().st_size, sha(remote), flush=True)
    (OUT / 'verified.json').write_text(json.dumps({
        'id':r['id'],'assets':{p.name:sha(p) for p in (DELTA,FULL)}}))

def publish():
    from datetime import datetime, timezone
    assert datetime.now(timezone.utc) >= datetime(2026,11,14,9,19,tzinfo=timezone.utc), 'Publication before official release time forbidden'
    r = release_verify()
    proof = json.loads((OUT / 'verified.json').read_text())
    assert proof == {'id':r['id'],'assets':{p.name:sha(p) for p in (DELTA,FULL)}}
    api(f'repos/{REPO}/releases/{r["id"]}', {'draft':False,'make_latest':'true'}, method='PATCH')
    r = release_verify()
    assert not r['draft']
    assert api(f'repos/{REPO}/releases/tags/{TAG}')['id'] == r['id']
    print('Published verified release', r['id'], flush=True)

def candidate():
    m = json.loads((OUT / 'baseline-manifest.json').read_text())
    new = copy.deepcopy(m)
    new.update(version='1.0.0',
               downloadUrl=f'https://github.com/{REPO}/releases/download/{TAG}/{FULL.name}',
               sha256=sha(FULL), notes='Première sortie officielle : traduction française intégrale de l’arc Questions (épisodes 1 à 4).')
    package = {'id':'questions-100','downloadUrl':f'https://github.com/{REPO}/releases/download/{TAG}/{DELTA.name}',
               'sha256':sha(DELTA),'size':DELTA.stat().st_size}
    new['packages'].append(package)
    for item in new['files']:
        if item['path'] == '0.u':
            item.update(sha256=sha_bytes(source_files()['0.u']),size=18024811,packageId=package['id'])
    (OUT / 'candidate-manifest.json').write_text(json.dumps(new,ensure_ascii=False))
    return new

def activate():
    r = release_verify()
    assert not r['draft'] and not r['prerelease']
    current = api(f'repos/{REPO}/contents/update/manifest.json?ref=main')
    m = json.loads(base64.b64decode(current['content']))
    baseline = json.loads((OUT / 'baseline-manifest.json').read_text())
    assert m == baseline, 'Live manifest changed during publication; stop'
    files = source_files()
    new = copy.deepcopy(m)
    new['version'] = '1.0.0'
    new['downloadUrl'] = f'https://github.com/{REPO}/releases/download/{TAG}/{FULL.name}'
    new['sha256'] = sha(FULL)
    new['notes'] = 'Première sortie officielle : traduction française intégrale de l’arc Questions (épisodes 1 à 4).'
    package = {'id':'questions-100','downloadUrl':f'https://github.com/{REPO}/releases/download/{TAG}/{DELTA.name}',
               'sha256':sha(DELTA),'size':DELTA.stat().st_size}
    assert all(p['id'] != package['id'] for p in new['packages'])
    new['packages'].append(package)
    for item in new['files']:
        if item['path'] in files:
            b = files[item['path']]
            item.update(sha256=sha_bytes(b),size=len(b),packageId=package['id'])
    assert len(new['files']) == len(m['files']) == 4047
    assert len(new['packages']) == 23
    assert new['updater'] == m['updater']
    for before,after in zip(m['files'],new['files']):
        if before['path'] not in files:
            assert before == after
    # Simulate the existing updater's manifest hash comparison for a v0.1.23 client.
    needed = [a for a,b in zip(new['files'],m['files']) if a['sha256'] != b['sha256']]
    assert {x['path'] for x in needed} == set(files)
    assert {x['packageId'] for x in needed} == {'questions-100'}
    assert new == json.loads((OUT / 'candidate-manifest.json').read_text()), 'Candidate changed after compatibility validation'
    raw = json.dumps(new,ensure_ascii=False,separators=(',',':')).encode()
    api(f'repos/{REPO}/contents/update/manifest.json',{
        'message':'release: activate verified Umineko FR v1.0.0 Questions script only',
        'content':base64.b64encode(raw).decode(),'sha':current['sha'],'branch':'main'})
    live = api(f'repos/{REPO}/contents/update/manifest.json?ref=main')
    assert json.loads(base64.b64decode(live['content'])) == new
    print('SUCCESS: active manifest 1.0.0; 4047 files, 23 packages; existing updater unchanged')

if __name__ == '__main__':
    {'prepare':prepare,'build':build,'candidate':candidate,'create':create,'verify':verify,'publish':publish,'activate':activate}[sys.argv[1]]()
