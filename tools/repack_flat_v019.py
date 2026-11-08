#!/usr/bin/env python3
"""Produce a flat ZIP, verify against the existing V3 file manifest and publish v0.1.19."""
import base64
import hashlib
import json
import pathlib
import subprocess
import tempfile
import zipfile

REPO = "Naries5/umineko-fr"
SOURCE = "patch-fr-0.1.18.zip"
TARGET = "patch-fr-0.1.19.zip"
PREFIX = "patch-fr-0.1.18/"
SOURCE_SHA = "622e88ec177f65b212b70ef6c98dda162387bedaad6411ea771f23c247544797"

def sha(path):
    result=hashlib.sha256()
    with open(path,"rb") as inp:
        for block in iter(lambda: inp.read(1048576), b""):
            result.update(block)
    return result.hexdigest()

def run(*args):
    subprocess.run(args,check=True)

def main():
    with tempfile.TemporaryDirectory(prefix="umineko-flat-") as tmp:
        folder=pathlib.Path(tmp)
        run("gh","release","download","v0.1.18","--repo",REPO,
            "--pattern",SOURCE,"--dir",str(folder))
        original=folder/SOURCE
        if sha(original)!=SOURCE_SHA:
            raise RuntimeError("Original ZIP hash mismatch")
        current=json.loads(subprocess.check_output(
            ["gh","api",f"repos/{REPO}/contents/update/manifest.json"]))
        manifest=json.loads(base64.b64decode(current["content"]).decode())
        if manifest.get("version")!="0.1.18" or manifest.get("schemaVersion")!=3:
            raise RuntimeError("Live manifest changed, aborting")
        expected={f["path"].replace("\\","/"):f["sha256"] for f in manifest["files"]}
        seen=set()
        new=folder/TARGET
        with zipfile.ZipFile(original) as src,zipfile.ZipFile(
            new,"w",compression=zipfile.ZIP_DEFLATED,compresslevel=5,
            allowZip64=True) as dst:
            for member in src.infolist():
                if member.is_dir():
                    continue
                old_name=member.filename.replace("\\","/")
                if not old_name.startswith(PREFIX):
                    raise RuntimeError("Unexpected root "+old_name)
                name=old_name[len(PREFIX):]
                if name not in expected or name in seen:
                    raise RuntimeError("Unexpected or duplicate file "+name)
                if any(segment in ("",".","..") for segment in name.split("/")) or ":" in name:
                    raise RuntimeError("Unsafe path "+name)
                h=hashlib.sha256()
                with src.open(member) as input_stream,dst.open(name,"w",force_zip64=True) as output:
                    while chunk:=input_stream.read(1048576):
                        h.update(chunk)
                        output.write(chunk)
                if h.hexdigest()!=expected[name]:
                    raise RuntimeError("File hash mismatch "+name)
                seen.add(name)
        if seen!=set(expected):
            raise RuntimeError("Missing expected files "+str(sorted(set(expected)-seen)[:8]))
        with zipfile.ZipFile(new) as check:
            if "0.u" not in check.namelist() or check.testzip() is not None:
                raise RuntimeError("Output ZIP failed integrity test")
        print("Validated flat ZIP with",len(seen),"files",flush=True)

        # Create draft first; only publicize fully validated assets.
        run("gh","release","create","v0.1.19","--repo",REPO,
            "--target","main","--title","v0.1.19 - Correction installation",
            "--notes","Archive corrigee : 0.u, bmp et en directement a la racine. Les packages V3 restent disponibles.",
            "--draft")
        run("gh","release","upload","v0.1.19",str(new),"--repo",REPO)
        release=json.loads(subprocess.check_output([
            "gh","api",f"repos/{REPO}/releases/tags/v0.1.19"]))
        assets=[a for a in release["assets"] if a["name"]==TARGET]
        new_hash=sha(new)
        if len(assets)!=1 or assets[0]["size"]!=new.stat().st_size or assets[0]["digest"]!="sha256:"+new_hash:
            raise RuntimeError("Release asset validation failed")
        run("gh","release","edit","v0.1.19","--repo",REPO,"--draft=false")

        manifest["version"]="0.1.19"
        manifest["downloadUrl"]=f"https://github.com/{REPO}/releases/download/v0.1.19/{TARGET}"
        manifest["sha256"]=new_hash
        manifest["notes"]="Correction installation : fichiers a la racine du jeu; verification de la version 0.1.18."
        body=json.dumps({
            "message":"fix: flat 0.1.19 legacy archive and force 0.1.18 verification",
            "content":base64.b64encode(
                (json.dumps(manifest,ensure_ascii=False,indent=2)+"\n").encode()
            ).decode(),
            "sha":current["sha"],
            "branch":"main"
        })
        subprocess.run(["gh","api","--method","PUT",
            f"repos/{REPO}/contents/update/manifest.json","--input","-"],
            input=body,text=True,check=True,stdout=subprocess.DEVNULL)
        print("SUCCESS: flat v0.1.19 published and manifest switched",flush=True)

if __name__=="__main__":
    main()
