#!/usr/bin/env python3
"""Finalize verified flat v0.1.19 draft and switch legacy + V3 manifest.
Called only after prior workflow validated the contents of every ZIP member.
"""
import base64, json, subprocess

REPO="Naries5/umineko-fr"
DRAFT_ID=438210468
ARCHIVE="patch-fr-0.1.19.zip"
SHA="fa583e5a3d9ccf838862f2b95be2718874d262eddd900d32f28a344c6fd358e4"
SIZE=1102371574

def output(*args):
    return subprocess.check_output(args,text=True).strip()

def run(*args):
    subprocess.run(args,check=True)

def main():
    release=json.loads(output("gh","api",f"repos/{REPO}/releases/{DRAFT_ID}"))
    if release.get("tag_name")!="v0.1.19" or release.get("name")!="v0.1.19 - Correction installation":
        raise RuntimeError("Unexpected release identity")
    asset=[a for a in release["assets"] if a["name"]==ARCHIVE]
    if len(asset)!=1 or asset[0]["state"]!="uploaded" or asset[0]["size"]!=SIZE or asset[0]["digest"]!="sha256:"+SHA:
        raise RuntimeError("Unverified release archive")
    current=json.loads(output("gh","api",f"repos/{REPO}/contents/update/manifest.json"))
    manifest=json.loads(base64.b64decode(current["content"]).decode("utf-8"))
    if manifest.get("version")!="0.1.18" or manifest.get("schemaVersion")!=3 or len(manifest.get("files",[]))!=4047:
        raise RuntimeError("Manifest changed; not safe to switch")
    if release.get("draft"):
        run("gh","release","edit","v0.1.19","--repo",REPO,"--draft=false")
    published=json.loads(output("gh","api",f"repos/{REPO}/releases/tags/v0.1.19"))
    if published.get("draft") or published.get("id")!=DRAFT_ID:
        raise RuntimeError("Release not public")
    manifest["version"]="0.1.19"
    manifest["downloadUrl"]=f"https://github.com/{REPO}/releases/download/v0.1.19/{ARCHIVE}"
    manifest["sha256"]=SHA
    manifest["notes"]="Correction installation : 0.u, bmp et en directement dans le dossier du jeu. Compatible avec les anciens patchers."
    request=json.dumps({
        "message":"fix: publish v0.1.19 flat ZIP and force correction for installed v0.1.18",
        "sha":current["sha"],
        "branch":"main",
        "content":base64.b64encode((json.dumps(manifest,ensure_ascii=False,indent=2)+"\n").encode()).decode()
    })
    subprocess.run(["gh","api","--method","PUT",f"repos/{REPO}/contents/update/manifest.json",
                    "--input","-"],input=request,text=True,check=True,stdout=subprocess.DEVNULL)
    print("SUCCESS: v0.1.19 published, validated, manifest updated. 18 V3 packages preserved.",flush=True)

if __name__=="__main__":
    main()
