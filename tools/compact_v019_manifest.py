#!/usr/bin/env python3
"""Compact the public manifest without changing any value or updater behavior.

Older patchers have a hard-coded 20-second HttpClient timeout. Minifying cuts
transfer bytes, but does not guarantee success on an unavailable network.
"""
import base64, json, subprocess

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
