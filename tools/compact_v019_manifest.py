#!/usr/bin/env python3
"""Compact the public manifest without changing any value or updater behavior.

Older patchers have a hard-coded 20-second HttpClient timeout. Minifying cuts
transfer bytes, but does not guarantee success on an unavailable network.
"""
import base64, json, subprocess

# Run the authorized v0.1.23 publication through this existing contents-write
# workflow. The original v0.1.19 compaction below remains untouched.
from pathlib import Path
import sys
if __name__ == '__main__' and Path('.staging/v0.1.23/chunks/009.part').is_file():
    version = json.loads(Path('update/manifest.json').read_text())['version']
    if version == '0.1.22':
        from run_v023 import main
        main()
        sys.exit(0)
    if version == '0.1.23':
        print('v0.1.23 already active; no changes made', flush=True)
        sys.exit(0)


repo="Naries5/umineko-fr"
def read(*args):
    return subprocess.check_output(args,text=True)

doc=json.loads(read("gh","api",f"repos/{repo}/contents/update/manifest.json"))
original=base64.b64decode(doc["content"])
manifest=json.loads(original)
if (manifest.get("schemaVersion"), manifest.get("version")) != (3, "0.1.19"):
    raise RuntimeError("Unexpected manifest schema/version")
if len(manifest.get("files",[])) != 4047 or len(manifest.get("packages",[])) != 18:
    raise RuntimeError("Unexpected manifest content")
compressed=json.dumps(manifest,ensure_ascii=False,separators=(",",":")).encode("utf-8")+b"\n"
if json.loads(compressed) != manifest:
    raise RuntimeError("Compacted manifest differs from original")
if len(compressed)>=len(original):
    raise RuntimeError("No manifest size improvement")
print(f"Size before: {len(original)} bytes; after: {len(compressed)} bytes",flush=True)
payload=json.dumps({
    "message":"perf: compact v0.1.19 manifest to reduce old patcher 20s fetch time",
    "content":base64.b64encode(compressed).decode("ascii"),
    "sha":doc["sha"],
    "branch":"main"
})
subprocess.run(["gh","api","--method","PUT",
                f"repos/{repo}/contents/update/manifest.json","--input","-"],
               input=payload,text=True,check=True,stdout=subprocess.DEVNULL)
print("SUCCESS: manifest compacted without changing any data",flush=True)
