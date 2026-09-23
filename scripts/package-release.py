#!/usr/bin/env python3
"""Deterministic source-kit archive with per-member hashes; does not build an OS image."""
import hashlib
import stat
import sys
import zipfile
from pathlib import Path

root = Path(__file__).resolve().parents[1]
output = Path(sys.argv[1]).resolve()
output.parent.mkdir(parents=True, exist_ok=True)
if output.exists():
    raise SystemExit("Refusing to overwrite an existing release archive")
skip = {".git", ".venv", "__pycache__", ".pytest_cache", "build", "dist", "node_modules"}
members = {}
for p in sorted(root.rglob("*")):
    rel = p.relative_to(root)
    if any(x in skip or x.endswith(".egg-info") for x in rel.parts):
        continue
    if p.is_symlink():
        raise SystemExit("Release symlink refused: " + str(rel))
    if not p.is_file() or p.suffix in {".pyc", ".pyo"} or p.name == "SOURCE_MANIFEST.sha256":
        continue
    if p.name.startswith(".env") or "credentials.txt" in p.name or p.name in {"config.json", "secrets.json"}:
        raise SystemExit("Private file refused: " + str(rel))
    members[str(rel)] = (p.read_bytes(), p.stat().st_mode)
manifest = "".join(hashlib.sha256(data).hexdigest() + "  " + name + "\n"
                   for name, (data, mode) in members.items())
members["SOURCE_MANIFEST.sha256"] = (manifest.encode(), 0o100644)
with zipfile.ZipFile(output, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for name, (data, mode) in sorted(members.items()):
        info = zipfile.ZipInfo("smilyai-os/" + name, date_time=(2026, 9, 22, 0, 0, 0))
        info.create_system = 3
        info.external_attr = (stat.S_IFREG | (mode & 0o777)) << 16
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, data)
with zipfile.ZipFile(output) as archive:
    if archive.testzip() is not None:
        raise SystemExit("Archive CRC validation failed")
print("Members:", len(members))
print("Bytes:", output.stat().st_size)
print("SHA256:", hashlib.sha256(output.read_bytes()).hexdigest())
print(output)
