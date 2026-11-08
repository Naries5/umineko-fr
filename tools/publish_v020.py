#!/usr/bin/env python3
"""Publish v0.1.20 with the exact user-provided Questions 0.u.
The manifest is switched only after both release assets pass SHA-256 checks.
"""
import base64
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

REPO = "Naries5/umineko-fr"
TAG = "v0.1.20"
OLD_TAG = "v0.1.19"
EXPECTED_0U_SHA = "86ac56ba03e4e38b7cd3298d11b5b3cfa0234980a45ba0173c2f66746ba8adfb"
EXPECTED_0U_BYTES = 18054729
EXPECTED_PREVIOUS_0U_SHA = "1ffa7b4a4238606d2c0d4fd47d523c3031008a783c6dbef8b19331f95ad29796"
EXPECTED_PREVIOUS_FULL_SHA = "fa583e5a3d9ccf838862f2b95be2718874d262eddd900d32f28a344c6fd358e4"
EXPECTED_UPDATER_SHA = "95b72b0ae8593ba0546261af9e9277d1a844d8e4813667c1453e6c437b2369a0"
SOURCE = Path(".staging/v0.1.20/chunks")
OUT = Path("publish")
USER_SCRIPT = OUT / "0.u"
DELTA = OUT / "UminekoFR-Questions-0.1.20.zip"
FULL = OUT / "patch-fr-0.1.20.zip"
OLD_FULL = Path("old-release/patch-fr-0.1.19.zip")


def sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as handle:
        while chunk := handle.read(2 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def check_0u():
    assert USER_SCRIPT.exists(), "Reconstructed 0.u not found"
    assert USER_SCRIPT.stat().st_size == EXPECTED_0U_BYTES, "Unexpected 0.u size"
    assert sha(USER_SCRIPT) == EXPECTED_0U_SHA, "0.u differs from user-provided file"
    assert USER_SCRIPT.read_bytes().startswith(b"\xef\xbb\xbf"), "0.u BOM altered"
    assert USER_SCRIPT.read_bytes().count(b"\n") == 342483, "Line count changed"


def prepare():
    parts = sorted(SOURCE.glob("*.part"))
    assert len(parts) == 69, f"Expected 69 staging pieces; got {len(parts)}"
    assert [p.name for p in parts] == [f"{n:03d}.part" for n in range(69)], "Missing staging chunk"
    OUT.mkdir(exist_ok=True)
    with USER_SCRIPT.open("wb") as target:
        for part in parts:
            target.write(part.read_bytes())
    check_0u()
    with zipfile.ZipFile(DELTA, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.write(USER_SCRIPT, "0.u")
    with zipfile.ZipFile(DELTA) as z:
        assert z.namelist() == ["0.u"], "Delta package has incorrect paths"
        assert hashlib.sha256(z.read("0.u")).hexdigest() == EXPECTED_0U_SHA
    print(f"DELTA READY: bytes={DELTA.stat().st_size} sha256={sha(DELTA)}")
    print(f"USER 0.u VERIFIED: {EXPECTED_0U_SHA}")


def build_legacy():
    check_0u()
    assert OLD_FULL.exists(), "Original v0.1.19 full ZIP is missing"
    assert sha(OLD_FULL) == EXPECTED_PREVIOUS_FULL_SHA, "v0.1.19 ZIP checksum invalid"

    with zipfile.ZipFile(OLD_FULL) as old:
        files_before = {x.filename: (x.file_size, x.CRC) for x in old.infolist() if not x.is_dir()}
        assert "0.u" in files_before and len(files_before) == 4047, (
            f"Unexpected v0.1.19 archive layout: {len(files_before)} files")
        assert hashlib.sha256(old.read("0.u")).hexdigest() == EXPECTED_PREVIOUS_0U_SHA, (
            "Unexpected original 0.u")

    shutil.copyfile(OLD_FULL, FULL)
    subprocess.run(["zip", "-q", "-d", str(FULL), "0.u"], check=True)
    subprocess.run(["zip", "-q", "-6", FULL.name, "0.u"], check=True, cwd=OUT)
    # The working directory is OUT; zip's output path above must be OUT-relative.
    with zipfile.ZipFile(FULL) as new:
        files_after = {x.filename: (x.file_size, x.CRC) for x in new.infolist() if not x.is_dir()}
        assert set(files_after) == set(files_before), "Files added/removed from full ZIP"
        assert len(new.namelist()) == len(set(new.namelist())), "Duplicate ZIP entry"
        assert hashlib.sha256(new.read("0.u")).hexdigest() == EXPECTED_0U_SHA
        for name, metadata in files_before.items():
            if name != "0.u":
                assert files_after[name] == metadata, f"Unrelated file changed: {name}"
    print(f"LEGACY READY: bytes={FULL.stat().st_size} sha256={sha(FULL)}")


def gh_api(*args, input_data=None):
    argv = ["gh", "api", *args]
    if input_data is not None:
        p = subprocess.run(argv, input=json.dumps(input_data), text=True, capture_output=True)
    else:
        p = subprocess.run(argv, text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(f"GitHub API failed: {p.stderr}")
    return json.loads(p.stdout) if p.stdout.strip() else {}


def activate():
    check_0u()
    for target in (DELTA, FULL):
        assert target.exists(), f"Missing published asset: {target}"
    release = gh_api(f"repos/{REPO}/releases/tags/{TAG}")
    assert not release["draft"] and not release["prerelease"], "Release must be public"
    by_name = {asset["name"]: asset for asset in release["assets"]}
    for target in (DELTA, FULL):
        asset = by_name[target.name]
        assert asset["state"] == "uploaded", f"Release asset not ready: {target.name}"
        assert asset["size"] == target.stat().st_size, f"Release size mismatch: {target.name}"
        assert asset.get("digest") == f"sha256:{sha(target)}", (
            f"Release hash mismatch: {target.name}")

    current = gh_api(f"repos/{REPO}/contents/update/manifest.json")
    manifest = json.loads(base64.b64decode(current["content"]).decode("utf-8"))
    assert manifest["version"] == "0.1.19" and manifest["schemaVersion"] == 3, (
        "Existing manifest changed; cancel v0.1.20 rollout")
    assert len(manifest["files"]) == 4047 and len(manifest["packages"]) == 18
    assert manifest["updater"]["sha256"] == EXPECTED_UPDATER_SHA, (
        "Unexpected updater in manifest")
    assert manifest["sha256"] == EXPECTED_PREVIOUS_FULL_SHA
    matches = [item for item in manifest["files"] if item["path"] == "0.u"]
    assert len(matches) == 1 and matches[0]["sha256"] == EXPECTED_PREVIOUS_0U_SHA, (
        "Unexpected Questions script in manifest")

    name = "questions-020"
    assert all(p["id"] != name for p in manifest["packages"])
    manifest["version"] = "0.1.20"
    manifest["downloadUrl"] = f"https://github.com/{REPO}/releases/download/{TAG}/{FULL.name}"
    manifest["sha256"] = sha(FULL)
    manifest["notes"] = "Mise à jour de la traduction Questions (0.u), sans modification des autres fichiers."
    matches[0]["sha256"] = EXPECTED_0U_SHA
    matches[0]["size"] = EXPECTED_0U_BYTES
    matches[0]["packageId"] = name
    manifest["packages"].append({
        "id": name,
        "downloadUrl": f"https://github.com/{REPO}/releases/download/{TAG}/{DELTA.name}",
        "sha256": sha(DELTA),
        "size": DELTA.stat().st_size,
    })
    assert len(manifest["files"]) == 4047 and len(manifest["packages"]) == 19
    assert manifest["updater"]["sha256"] == EXPECTED_UPDATER_SHA
    packed = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    payload = {
        "message": "release: activate verified Umineko FR v0.1.20 Questions script update",
        "content": base64.b64encode(packed).decode("ascii"),
        "sha": current["sha"],
        "branch": "main",
    }
    gh_api("--method", "PUT", f"repos/{REPO}/contents/update/manifest.json", "--input", "-", input_data=payload)
    checked = gh_api(f"repos/{REPO}/contents/update/manifest.json")
    live = json.loads(base64.b64decode(checked["content"]).decode("utf-8"))
    assert live == manifest, "Manifest post-publication readback mismatch"
    print(f"SUCCESS: v0.1.20 activated, 4047 files, 19 packages, updater unchanged")


if __name__ == "__main__":
    commands = {"prepare": prepare, "build-legacy": build_legacy, "activate": activate}
    if len(sys.argv) != 2 or sys.argv[1] not in commands:
        raise SystemExit(f"Usage: {sys.argv[0]} " + " | ".join(commands))
    commands[sys.argv[1]]()
