#!/usr/bin/env python3
"""Stage reviewed runtime inputs, never the developer's whole checkout."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
SOURCE = Path(__file__).resolve().parents[1]
def stage(destination):
    root = Path(destination).resolve()
    app = root / "opt/smilyai-os"
    app.mkdir(parents=True, exist_ok=True)
    records = {}
    for directory, suffixes in (("smilyai", {".py"}), ("shell", {".js", ".css", ".html", ".png", ".svg", ".woff2"})):
        for src in sorted((SOURCE / directory).rglob("*")):
            if src.is_symlink():
                raise ValueError(f"Runtime symlink refused: {src}")
            if not src.is_file() or src.suffix not in suffixes or any(p.startswith(".") or p == "__pycache__" for p in src.relative_to(SOURCE).parts):
                continue
            relative = src.relative_to(SOURCE)
            target = app / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            target.chmod(0o644)
            records[str(relative)] = hashlib.sha256(src.read_bytes()).hexdigest()
    shutil.copyfile(SOURCE / "LICENSE", app / "LICENSE")
    overlay = SOURCE / "packaging/rootfs"
    for src in sorted(overlay.rglob("*")):
        if src.is_symlink():
            raise ValueError("Overlay symlinks are not permitted")
        if src.is_file():
            target = root / src.relative_to(overlay)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, target)
            target.chmod(0o755 if src.read_bytes().startswith(b"#!") else 0o644)
    (app / "runtime-manifest.json").write_text(json.dumps(records, indent=2) + "\n")
    (root / "etc/smilyai-release").write_text("SmilyAI OS 0.3.1 preview\n")
    return records
if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: stage-runtime.py EMPTY_ROOTFS_OVERLAY")
    stage(sys.argv[1])
