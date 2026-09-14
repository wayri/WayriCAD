"""Read Git snapshots without checkout, hooks, filters, or repository mutation."""

from pathlib import Path, PurePosixPath
import os
import subprocess


class VizError(Exception):
    """An actionable user-facing failure."""


def run(args, cwd=None, timeout=120, data=None):
    try:
        result = subprocess.run(args, cwd=cwd, input=data, capture_output=True, timeout=timeout,
                                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise VizError(f"Could not run {args[0]}: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout).decode("utf-8", "replace").strip()
        raise VizError(f"{args[0]} failed ({result.returncode}): {detail}")
    return result.stdout


def git(repo, *args, data=None):
    return run(["git", "-C", str(repo), *args], data=data)


def root(repo):
    return Path(git(repo, "rev-parse", "--show-toplevel").decode().strip()).resolve()


def resolve(repo, ref):
    return git(repo, "rev-parse", "--verify", "--end-of-options", ref + "^{commit}").decode().strip()


def safe_path(root_dir, name):
    path = PurePosixPath(name)
    if (path.is_absolute() or not path.parts or any(p in ("..", ".git") for p in path.parts)
            or "\\" in name or ":" in name):
        raise VizError(f"Unsafe repository path: {name!r}")
    target = root_dir.joinpath(*path.parts)
    if not target.resolve().is_relative_to(root_dir.resolve()):
        raise VizError(f"Path escapes project: {name!r}")
    return target


def snapshot(repo, ref, destination, max_bytes=250 * 1024 * 1024):
    """Materialize regular blobs only; retain project-relative libraries and sheets."""
    destination.mkdir(parents=True, exist_ok=True)
    total = 0
    if ref == "WORKTREE":
        names = git(repo, "ls-files", "-z", "--cached", "--others", "--exclude-standard").split(b"\0")
        for raw in dict.fromkeys(names):
            if not raw:
                continue
            name = raw.decode("utf-8")
            source = safe_path(repo, name)
            if source.is_symlink():
                raise VizError(f"Symlinks are not supported in snapshots: {name}")
            if not source.exists():
                continue  # A tracked file deleted in the working tree.
            if not source.is_file():
                raise VizError(f"Submodules/directories are not supported: {name}")
            total += source.stat().st_size
            if total > max_bytes:
                raise VizError("Snapshot exceeds 250 MiB; use a smaller hardware repository.")
            target = safe_path(destination, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(source.read_bytes())
        return "WORKTREE"
    commit = resolve(repo, ref)
    entries = git(repo, "ls-tree", "-r", "-z", commit).split(b"\0")
    for entry in entries:
        if not entry:
            continue
        meta, name_bytes = entry.split(b"\t", 1)
        mode, kind, oid = meta.decode().split()
        name = name_bytes.decode("utf-8")
        if kind != "blob" or mode not in ("100644", "100755"):
            raise VizError(f"Symlinks and submodules are not supported in snapshots: {name}")
        size = int(git(repo, "cat-file", "-s", oid))
        total += size
        if total > max_bytes:
            raise VizError("Snapshot exceeds 250 MiB; use a smaller hardware repository.")
        target = safe_path(destination, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        blob = git(repo, "cat-file", "blob", oid)
        if blob.startswith(b"version https://git-lfs.github.com/spec/v1"):
            raise VizError(f"Git LFS pointers are unsupported; materialize assets and use WORKTREE: {name}")
        target.write_bytes(blob)
    return commit
