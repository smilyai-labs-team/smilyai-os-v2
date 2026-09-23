from __future__ import annotations
import ctypes
import errno
import mimetypes
import os
import stat
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote

class PathSandbox:
    """Directory-fd rooted operations; no symlink components or hidden paths."""
    def __init__(self, roots=None):
        self.roots = [Path(os.path.expanduser(r)).resolve() for r in (roots or ["~"])]

    def resolve(self, value, *, must_exist=False):
        if not isinstance(value, str) or not value or "\x00" in value:
            raise ValueError("Invalid path")
        p = Path(os.path.expanduser(value))
        if not p.is_absolute():
            p = Path.home() / p
        if ".." in p.parts:
            raise PermissionError("Parent traversal is not allowed")
        p = Path(os.path.abspath(p))
        root = next((r for r in self.roots if p == r or r in p.parents), None)
        if root is None:
            raise PermissionError("Path is outside the allowed user locations")
        current = root
        for part in p.relative_to(root).parts:
            if part.startswith("."):
                raise PermissionError("Hidden configuration and credential files are excluded")
            current /= part
            if current.is_symlink():
                raise PermissionError("Symlinks are not followed by AI file tools")
        if must_exist and not p.exists():
            raise FileNotFoundError("File not found")
        return p

    @contextmanager
    def parent(self, value):
        p = self.resolve(value)
        root = next(r for r in self.roots if p == r or r in p.parents)
        parts = p.relative_to(root).parts
        if not parts:
            raise PermissionError("The allowed root itself cannot be modified")
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            for part in parts[:-1]:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new
            yield fd, parts[-1], p
        finally:
            os.close(fd)

    @contextmanager
    def directory(self, value):
        p = self.resolve(value, must_exist=True)
        if p in self.roots:
            fd = os.open(p, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        else:
            with self.parent(str(p)) as (parent, name, _):
                fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
        try:
            yield fd, p
        finally:
            os.close(fd)

def rename_no_replace(src_fd, src, dst_fd, dst):
    libc = ctypes.CDLL(None, use_errno=True)
    fn = getattr(libc, "renameat2", None)
    if fn is None:
        raise RuntimeError("Safe atomic move is unavailable on this platform")
    if fn(src_fd, os.fsencode(src), dst_fd, os.fsencode(dst), 1) != 0:
        e = ctypes.get_errno()
        if e == errno.EXDEV:
            raise ValueError("Cross-filesystem move is not supported; copy then Trash") from None
        raise OSError(e, os.strerror(e))

class FileTools:
    def __init__(self, sandbox):
        self.sandbox = sandbox

    def list_files(self, path="~", limit=80):
        items = []
        with self.sandbox.directory(path) as (fd, p):
            for name in sorted(os.listdir(fd), key=str.casefold):
                if name.startswith("."):
                    continue
                try:
                    s = os.stat(name, dir_fd=fd, follow_symlinks=False)
                    if not (stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode)):
                        continue
                    items.append({"name": name, "path": str(p / name), "kind": "folder" if stat.S_ISDIR(s.st_mode) else "file", "size": s.st_size, "modified": s.st_mtime})
                except OSError:
                    continue
                if len(items) >= limit:
                    break
        return {"path": str(p), "items": items, "surface": "files"}

    def read_file(self, path, max_bytes=262144):
        with self.sandbox.parent(path) as (fd, name, p):
            f = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            with os.fdopen(f, "rb") as stream:
                if not stat.S_ISREG(os.fstat(f).st_mode):
                    raise ValueError("Only regular files can be read")
                content = stream.read(max_bytes + 1)
            if len(content) > max_bytes:
                raise ValueError("File is too large")
        return {"path": str(p), "content": content.decode("utf-8", errors="replace"), "size": len(content)}

    def create_folder(self, path):
        with self.sandbox.parent(path) as (fd, name, p):
            os.mkdir(name, mode=0o700, dir_fd=fd)
        return {"path": str(p), "created": True, "surface": "success"}

    def move_file(self, source, destination):
        with self.sandbox.parent(source) as (sf, sn, sp), self.sandbox.parent(destination) as (df, dn, dp):
            rename_no_replace(sf, sn, df, dn)
        return {"source": str(sp), "destination": str(dp), "surface": "success"}

    rename_file = move_file

    def copy_file(self, source, destination):
        with self.sandbox.parent(source) as (sf, sn, sp), self.sandbox.parent(destination) as (df, dn, dp):
            source_fd = os.open(sn, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=sf)
            with os.fdopen(source_fd, "rb") as src:
                s = os.fstat(src.fileno())
                if not stat.S_ISREG(s.st_mode) or s.st_size > 64 * 1024 * 1024:
                    raise ValueError("Copy supports regular files up to 64 MiB; use the native file manager for folders")
                dest_fd = os.open(dn, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=df)
                try:
                    with os.fdopen(dest_fd, "wb") as dst:
                        remaining = 64 * 1024 * 1024
                        while remaining:
                            chunk = src.read(min(65536, remaining))
                            if not chunk:
                                break
                            dst.write(chunk)
                            remaining -= len(chunk)
                        if src.read(1):
                            raise ValueError("Source grew beyond the copy limit")
                except Exception:
                    os.unlink(dn, dir_fd=df)
                    raise
        return {"source": str(sp), "destination": str(dp), "surface": "success"}

    def delete_file(self, path, permanent=False):
        if permanent:
            raise PermissionError("Permanent deletion is not exposed to the AI")
        p = self.sandbox.resolve(path, must_exist=True)
        if p in self.sandbox.roots:
            raise PermissionError("Cannot Trash an allowed root")
        trash = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "Trash"
        if not trash.is_absolute():
            raise PermissionError("Trash location must be absolute")
        for current in (trash, *trash.parents):
            if current.is_symlink():
                raise PermissionError("Unsafe Trash directory")
        for sub in ("files", "info"):
            (trash / sub).mkdir(parents=True, exist_ok=True, mode=0o700)
        # Trash must be a trusted user-owned directory, not a redirected symlink.
        if (trash / "files").is_symlink():
            raise PermissionError("Unsafe Trash directory")
        if (trash / "info").is_symlink():
            raise PermissionError("Unsafe Trash metadata directory")
        import secrets
        name = p.name + "-" + secrets.token_hex(6)
        info = trash / "info" / (name + ".trashinfo")
        with info.open("x", encoding="utf-8") as f:
            f.write("[Trash Info]\nPath=" + quote(str(p), safe="/") + "\nDeletionDate=" + time.strftime("%Y-%m-%dT%H:%M:%S") + "\n")
        try:
            with self.sandbox.parent(path) as (sf, sn, _):
                df = os.open(trash / "files", os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    rename_no_replace(sf, sn, df, name)
                finally:
                    os.close(df)
        except Exception:
            info.unlink(missing_ok=True)
            raise
        return {"path": str(p), "trash_path": str(trash / "files" / name), "permanent": False}

    def search_files(self, query, path="~", limit=50):
        # Bounded breadth-first traversal, each directory opened without symlinks.
        pending, matches, visited = [path], [], 0
        while pending and visited < 500 and len(matches) < limit:
            current = pending.pop(0)
            visited += 1
            try:
                entries = self.list_files(current, 200)["items"]
                for item in entries:
                    if query.casefold() in item["name"].casefold():
                        matches.append(item)
                    if item["kind"] == "folder":
                        pending.append(item["path"])
                    if len(matches) >= limit:
                        break
            except (OSError, ValueError):
                continue
        return {"matches": matches, "query": query, "truncated": bool(pending), "surface": "files"}
