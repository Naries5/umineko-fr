#!/usr/bin/env python3
"""Rebuild v0.1.18's file-level update manifest from the existing Release ZIP.

Safe publication order: download + validate -> build + validate -> upload every
package -> verify assets -> publish manifest.json LAST. No game files are edited.
"""
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import zipfile

OWNER_REPO = "Naries5/umineko-fr"
VERSION = "0.1.18"
TAG = "v" + VERSION
SOURCE = "patch-fr-0.1.18.zip"
EXPECTED_SHA = "622e88ec177f65b212b70ef6c98dda162387bedaad6411ea771f23c247544797"
TARGET_RAW_BYTES = 64 * 1024 * 1024
GITHUB = "https://github.com/" + OWNER_REPO
EXCLUDED = {
    "umineko_fr_version.txt", "umineko_fr_state.json",
    "umineko_fr_updater.json", "backup_manifest.json",
}
UPDATER = {
    "version": "0.1.10",
    "downloadUrl": GITHUB + "/releases/download/v0.1.10/UminekoFR-Updater-win-x64.exe",
    "sha256": "7f90b1f79eab1919999d4737c965324686f3e9b1d0be9db0ae369f05a3d79a3f",
    "size": 35105077,
}

def cmd(*args, input=None):
    return subprocess.run(args, input=input, text=True, check=True,
                          stdout=subprocess.PIPE).stdout.strip()

def digest(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()

def safe_name(name):
    name = name.replace("\\", "/")
    parts = name.split("/")
    if (not name or name.startswith("/") or
        any(p in ("", ".", "..") for p in parts) or
        ":" in parts[0] or "\x00" in name):
        raise ValueError("Unsafe ZIP path: " + repr(name))
    return name

def main():
    with tempfile.TemporaryDirectory(prefix="umineko-release-") as tmp:
        workspace = pathlib.Path(tmp)
        source = workspace / SOURCE
        print("Downloading source from GitHub Release...", flush=True)
        subprocess.run(["gh", "release", "download", TAG, "--repo", OWNER_REPO,
                        "--pattern", SOURCE, "--dir", str(workspace)],
                       check=True)
        if digest(source) != EXPECTED_SHA:
            raise RuntimeError("Source ZIP SHA-256 mismatch; refusing to publish")

        with zipfile.ZipFile(source, "r") as original:
            members = [x for x in original.infolist() if not x.is_dir()]
            if not members:
                raise RuntimeError("Empty source archive")
            names = [safe_name(x.filename) for x in members]
            print("ZIP sample:", names[:35], flush=True)
            # Allow a single enclosing folder only when it contains the game's
            # 0.u and all entries share the same prefix.
            prefix = ""
            if "0.u" not in names:
                candidates = [n[:-3] for n in names if n.endswith("/0.u")]
                candidates = [p for p in candidates if p and all(n.startswith(p) for n in names)]
                if len(candidates) == 1:
                    prefix = candidates[0]
                    names = [n[len(prefix):] for n in names]
                    print("Stripping verified archive root:", prefix, flush=True)
                else:
                    raise RuntimeError("0.u missing or ambiguous; archive layout: " + repr(names[:35]))

            seen = set()
            for name, info in zip(names, members):
                key = name.casefold()
                if key in seen:
                    raise RuntimeError("Duplicate path (case insensitive): " + name)
                seen.add(key)
                if info.flag_bits & 1:
                    raise RuntimeError("Encrypted ZIP entry: " + name)

            packages = []
            files = []
            entries = sorted(zip(names, members), key=lambda item: item[0])
            # Group by original (uncompressed) bytes; cap individual download
            # sizes without arbitrarily splitting individual game files.
            groups = []
            group, group_size = [], 0
            for name, member in entries:
                if (name.lower() in EXCLUDED or
                    name.startswith(".umineko_fr_backup/")):
                    continue
                if group and group_size + member.file_size > TARGET_RAW_BYTES:
                    groups.append(group)
                    group, group_size = [], 0
                group.append((name, member))
                group_size += member.file_size
            if group:
                groups.append(group)
            if not groups:
                raise RuntimeError("No patch files found")

            for i, group in enumerate(groups, 1):
                pid = "full-018-%03d" % i
                filename = pid + ".zip"
                target = workspace / filename
                print("Building", filename, "with", len(group), "files", flush=True)
                with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED,
                                     compresslevel=6, allowZip64=True) as out:
                    for name, member in group:
                        h = hashlib.sha256()
                        with original.open(member) as src, out.open(name, "w",
                                                                    force_zip64=True) as dst:
                            while True:
                                block = src.read(1024 * 1024)
                                if not block:
                                    break
                                h.update(block)
                                dst.write(block)
                        files.append({"path": name, "sha256": h.hexdigest(),
                                      "packageId": pid, "size": member.file_size})
                # Re-open all produced archives to catch packaging defects.
                with zipfile.ZipFile(target) as test:
                    if test.testzip() is not None:
                        raise RuntimeError("Corrupted package: " + filename)
                packages.append({"id": pid,
                                 "downloadUrl": GITHUB + "/releases/download/" + TAG + "/" + filename,
                                 "sha256": digest(target),
                                 "size": target.stat().st_size})

        manifest = {
            "schemaVersion": 3,
            "version": VERSION,
            "downloadUrl": GITHUB + "/releases/download/" + TAG + "/" + SOURCE,
            "sha256": EXPECTED_SHA,
            "notes": "Mise a jour 0.1.18; packages verifies pour mises a jour et reinstallations.",
            "requires07thMod": True,
            "updater": UPDATER,
            "packages": packages,
            "files": files,
        }
        if len({f["path"].casefold() for f in files}) != len(files):
            raise RuntimeError("Duplicate paths in final manifest")
        print("Validated", len(packages), "packages and", len(files), "files")
        print("Uploading packages before switching the public manifest...", flush=True)
        for i, package in enumerate(packages):
            filename = package["id"] + ".zip"
            subprocess.run(["gh", "release", "upload", TAG, str(workspace / filename),
                            "--repo", OWNER_REPO, "--clobber"], check=True)
        assets = json.loads(cmd("gh", "api",
            "repos/" + OWNER_REPO + "/releases/tags/" + TAG))
        asset_map = {a["name"]: a for a in assets["assets"]}
        for package in packages:
            asset = asset_map.get(package["id"] + ".zip")
            if not asset or asset["state"] != "uploaded" or asset["size"] != package["size"]:
                raise RuntimeError("Uploaded package missing or size mismatch: " + package["id"])

        # Optimistic concurrency: refuse to overwrite a manifest changed
        # since the workflow started and never publish partial packages.
        remote = json.loads(cmd("gh", "api",
            "repos/" + OWNER_REPO + "/contents/update/manifest.json"))
        import base64
        current = json.loads(base64.b64decode(remote["content"]).decode("utf-8"))
        if current["version"] != VERSION:
            raise RuntimeError("Manifest version changed; refusing to overwrite")
        payload = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
        body = json.dumps({
            "message": "fix(updater): restore v3 incremental manifest for 0.1.18",
            "content": base64.b64encode(payload.encode("utf-8")).decode("ascii"),
            "sha": remote["sha"], "branch": "main",
        })
        cmd("gh", "api", "--method", "PUT",
            "repos/" + OWNER_REPO + "/contents/update/manifest.json",
            "--input", "-", input=body)
        print("SUCCESS: complete v3 manifest published LAST", flush=True)

if __name__ == "__main__":
    main()
