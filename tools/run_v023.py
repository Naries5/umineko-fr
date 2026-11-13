#!/usr/bin/env python3
"""Run the v0.1.22 publication sequence for the exact v0.1.23 source."""
import subprocess
import sys

def run(*args):
    print('RUN', *args, flush=True)
    subprocess.run(args,check=True)

def main():
    run('python3','tools/publish_v023.py','prepare')
    run('gh','release','download','v0.1.22','--repo','Naries5/umineko-fr','--pattern','patch-fr-0.1.22.zip','--dir','old-release')
    run('python3','tools/publish_v023.py','build')
    run('python3','tools/publish_v023.py','candidate')
    with open('publish/http.log','w') as log:
        server = subprocess.Popen(['python3','-m','http.server','8765','--bind','127.0.0.1','--directory','publish'],stdout=log,stderr=log)
        try:
            run('dotnet','run','--project','tools/v023-compat/Compat.csproj','--configuration','Release','--','publish')
        finally:
            server.terminate()
            server.wait()
    for stage in ('create','verify','publish','activate'):
        run('python3','tools/publish_v023.py',stage)
    run('dotnet','run','--project','tools/v023-compat/Compat.csproj','--configuration','Release','--','publish','published')

if __name__ == '__main__': main()
