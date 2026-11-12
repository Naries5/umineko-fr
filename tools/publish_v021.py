#!/usr/bin/env python3
"""Publish only the 17 supplied Questions files; activate after remote verification."""
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
TAG = 'v0.1.21'
SOURCE_SHA = '8bd8e1fe3fa721342808f42eb99578c93eba2c62029477d5436dcc4af8e3bd88'
OLD_FULL_SHA = 'a329a1532cc3bf554e95b657980d5ca27c0fcb0d3dfc3f7cf51d18be8056b711'
OUT = Path('publish')
DELTA = OUT / 'UminekoFR-Questions-0.1.21.zip'
FULL = OUT / 'patch-fr-0.1.21.zip'
SOURCE = OUT / 'source.zip'
OLD = Path('old-release/patch-fr-0.1.20.zip')
BASE = Path('update/manifest.json')

def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()

def sha(p):
    with open(p, 'rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()

def run(*args):
    return subprocess.run(args, check=True, text=True, capture_output=True).stdout

def api(endpoint, payload=None):
    args = ['gh', 'api', endpoint]
    if payload is not None:
        args += ['--method', 'PUT', '--input', '-']
    p = subprocess.run(args, input=json.dumps(payload) if payload is not None else None,
                       text=True, capture_output=True, check=True)
    return json.loads(p.stdout)

def source_files():
    assert sha(SOURCE) == SOURCE_SHA, 'Supplied ZIP changed'
    with zipfile.ZipFile(SOURCE) as z:
        names = z.namelist()
        assert len(names) == len(set(names)) == 17
        assert '0.u' in names
        for n in names:
            assert not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts
            assert '\\' not in n and not n.endswith('/')
            assert n == '0.u' or (n.startswith('en/bmp/r_click/text/cha/') and n.endswith('.png'))
        assert z.testzip() is None
        return {n: z.read(n) for n in names}

def prepare():
    OUT.mkdir(exist_ok=True)
    parts = sorted(Path('.staging/v0.1.21/chunks').glob('*.part'))
    assert [p.name for p in parts] == [f'{i:03d}.part' for i in range(12)]
    with SOURCE.open('wb') as f:
        for p in parts:
            f.write(p.read_bytes())
    files = source_files()
    m = json.loads(BASE.read_text())
    assert m['version'] == '0.1.20' and m['schemaVersion'] == 3
    assert m['sha256'] == OLD_FULL_SHA
    index = {f['path']: f for f in m['files']}
    assert len(index) == len(m['files']) == 4047
    assert set(files) <= set(index), 'Unexpected new file'
    for n,b in files.items():
        assert sha_bytes(b) != index[n]['sha256'], 'Expected changed file'
    shutil.copyfile(BASE, OUT / 'baseline-manifest.json')
    shutil.copyfile(SOURCE, DELTA)
    print('Verified supplied archive: 17 changed files, exact source ZIP retained')

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
    shutil.copyfile(OLD, FULL)
    work = OUT / 'replacement'
    for n,b in files.items():
        p = work / n
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b)
    run('zip', '-q', '-d', str(FULL), *files)
    subprocess.run(['zip','-q','-6',str(FULL.resolve()),*files], cwd=work, check=True)
    with zipfile.ZipFile(FULL) as z:
        assert len(z.namelist()) == len(set(z.namelist()))
        assert {i.filename for i in z.infolist() if not i.is_dir()} == set(expected)
        for n,entry in expected.items():
            with z.open(n) as f:
                h = hashlib.file_digest(f, 'sha256').hexdigest()
            target = sha_bytes(files[n]) if n in files else entry['sha256']
            assert h == target, f'Full archive mismatch: {n}'
            assert z.getinfo(n).file_size == (len(files[n]) if n in files else entry['size'])
    print('Full archive verified: 17 replacements, 4030 other files byte-identical; no deletions')
    for p in (DELTA,FULL):
        print(p.name, p.stat().st_size, sha(p))

def release_verify():
    release = api(f'repos/{REPO}/releases/tags/{TAG}')
    assets = {a['name']:a for a in release['assets']}
    for p in (DELTA,FULL):
        a = assets[p.name]
        assert a['state'] == 'uploaded' and a['size'] == p.stat().st_size
        assert a['digest'] == 'sha256:' + sha(p)
    return release

def verify():
    release_verify()
    # Independently redownload the uploaded bytes, not only asset metadata.
    d = OUT / 'remote-verified'
    d.mkdir(exist_ok=True)
    run('gh','release','download',TAG,'--repo',REPO,'--dir',str(d),
        '--pattern',DELTA.name,'--pattern',FULL.name)
    for p in (DELTA,FULL):
        remote = d / p.name
        assert remote.stat().st_size == p.stat().st_size and sha(remote) == sha(p)
    print('Both uploaded archives redownloaded: exact SHA-256 and size confirmed')

def activate():
    r = release_verify()
    assert not r['draft'] and not r['prerelease']
    current = api(f'repos/{REPO}/contents/update/manifest.json?ref=main')
    m = json.loads(base64.b64decode(current['content']))
    baseline = json.loads((OUT / 'baseline-manifest.json').read_text())
    assert m == baseline, 'Live manifest changed during publication; stop'
    files = source_files()
    new = copy.deepcopy(m)
    new['version'] = '0.1.21'
    new['downloadUrl'] = f'https://github.com/{REPO}/releases/download/{TAG}/{FULL.name}'
    new['sha256'] = sha(FULL)
    new['notes'] = 'Mise à jour de la traduction Questions (EP1–4) et de 16 images.'
    package = {'id':'questions-021','downloadUrl':f'https://github.com/{REPO}/releases/download/{TAG}/{DELTA.name}',
               'sha256':sha(DELTA),'size':DELTA.stat().st_size}
    assert all(p['id'] != package['id'] for p in new['packages'])
    new['packages'].append(package)
    for item in new['files']:
        if item['path'] in files:
            b = files[item['path']]
            item.update(sha256=sha_bytes(b),size=len(b),packageId=package['id'])
    assert len(new['files']) == len(m['files']) == 4047
    assert len(new['packages']) == 20
    assert new['updater'] == m['updater']
    for before,after in zip(m['files'],new['files']):
        if before['path'] not in files:
            assert before == after
    # Simulate the existing updater's manifest hash comparison for a v0.1.20 client.
    needed = [a for a,b in zip(new['files'],m['files']) if a['sha256'] != b['sha256']]
    assert {x['path'] for x in needed} == set(files)
    assert {x['packageId'] for x in needed} == {'questions-021'}
    raw = json.dumps(new,ensure_ascii=False,separators=(',',':')).encode()
    api(f'repos/{REPO}/contents/update/manifest.json',{
        'message':'release: activate verified Umineko FR v0.1.21 Questions and images',
        'content':base64.b64encode(raw).decode(),'sha':current['sha'],'branch':'main'})
    live = api(f'repos/{REPO}/contents/update/manifest.json?ref=main')
    assert json.loads(base64.b64decode(live['content'])) == new
    print('SUCCESS: active manifest 0.1.21; 4047 files, 20 packages; existing updater unchanged')

if __name__ == '__main__':
    {'prepare':prepare,'build':build,'verify':verify,'activate':activate}[sys.argv[1]]()
