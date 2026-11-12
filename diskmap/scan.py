"""Fast disk scanner built on os.scandir.

Produces a size-annotated tree plus three derived views that make the map
actionable: the biggest files, duplicate groups, and large files nobody has
touched in a year.
"""

from __future__ import annotations

import hashlib
import os
import sys
import time

# Folders that are almost never worth mapping: they are either not user data
# or they are endless (Windows component store, package caches).
DEFAULT_EXCLUDES = {
    "$Recycle.Bin",
    "System Volume Information",
    "Windows.old",
    "$WinREAgent",
    "node_modules",
    ".git",
}

# Build artefacts and dependency caches: always regenerable, so this is the
# space a developer can win back without losing a single file they wrote.
# Matched case-insensitively, on directory name only.
JUNK_DIRS = {
    "node_modules": "deps",
    "target": "build",
    "build": "build",
    "dist": "build",
    ".gradle": "cache",
    ".next": "build",
    "__pycache__": "cache",
    ".venv": "venv",
    "venv": "venv",
    ".tox": "cache",
    ".pytest_cache": "cache",
    ".mypy_cache": "cache",
    ".ruff_cache": "cache",
    ".turbo": "cache",
    ".parcel-cache": "cache",
    "coverage": "build",
}

# Below this a duplicate is not worth the hashing time.
DUP_MIN_SIZE = 1024 * 1024
STALE_MIN_SIZE = 100 * 1024 * 1024
STALE_DAYS = 365

LARGE_FILE_LIMIT = 300
DUP_GROUP_LIMIT = 200
STALE_LIMIT = 200
JUNK_LIMIT = 40
CHILD_LIMIT = 80
NODE_BUDGET = 45_000


class Node:
    __slots__ = ("name", "size", "mtime", "children", "is_dir", "ext",
                 "count", "junk")

    def __init__(self, name, is_dir, mtime=0, junk=""):
        self.name = name
        self.size = 0
        self.count = 0 if is_dir else 1     # files at or below this node
        self.mtime = mtime
        self.children = [] if is_dir else None
        self.is_dir = is_dir
        self.ext = "" if is_dir else _ext(name)
        # "deps" / "build" / "cache" / "venv" for regenerable directories.
        self.junk = junk


def _ext(name: str) -> str:
    i = name.rfind(".")
    if i <= 0 or i == len(name) - 1:
        return ""
    return name[i + 1 :].lower()[:12]


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{int(n)}B"
        n /= 1024
    return f"{n:.1f}TB"


def scan(root: str, excludes=None, progress=True):
    """Walk *root* and return (root_node, stats).

    Iterative on an explicit stack: a recursive walk blows the interpreter
    stack on deep node_modules-style trees.
    """
    excludes = DEFAULT_EXCLUDES if excludes is None else excludes
    excludes = {e.lower() for e in excludes}

    root = os.path.abspath(root)
    root_node = Node(root, True, 0)
    stats = {"files": 0, "dirs": 0, "errors": 0, "bytes": 0}
    # size -> [paths] for duplicate candidates
    by_size: dict[int, list[tuple[str, str]]] = {}

    stack = [(root, root_node)]
    t0 = time.time()
    last_tick = t0

    while stack:
        path, node = stack.pop()
        try:
            entries = list(os.scandir(path))
        except OSError:
            stats["errors"] += 1
            continue

        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    name = entry.name
                    if name.lower() in excludes:
                        continue
                    # Junctions and reparse points can loop the walk forever.
                    if getattr(entry, "is_junction", lambda: False)():
                        continue
                    child = Node(name, True, junk=JUNK_DIRS.get(name.lower(), ""))
                    node.children.append(child)
                    stack.append((entry.path, child))
                    stats["dirs"] += 1
                else:
                    st = entry.stat(follow_symlinks=False)
                    child = Node(entry.name, False, st.st_mtime)
                    child.size = st.st_size
                    node.children.append(child)
                    stats["files"] += 1
                    stats["bytes"] += child.size
                    if child.size >= DUP_MIN_SIZE:
                        by_size.setdefault(child.size, []).append(
                            (entry.path, entry.name)
                        )
            except OSError:
                stats["errors"] += 1
                continue

        if progress:
            now = time.time()
            if now - last_tick > 1.0:
                last_tick = now
                sys.stderr.write(
                    f"\r  scanning  {_human(stats['bytes']):>9}  "
                    f"{stats['files']:,} files  {stats['dirs']:,} dirs   "
                )
                sys.stderr.flush()

    if progress:
        sys.stderr.write("\r" + " " * 78 + "\r")
        sys.stderr.flush()

    _rollup(root_node)

    largest = _largest_files(root_node, LARGE_FILE_LIMIT)
    stale = _stale_files(root_node, STALE_MIN_SIZE, STALE_DAYS, STALE_LIMIT)
    dups = _duplicates(by_size, DUP_GROUP_LIMIT, progress)
    junk = _junk_dirs(root_node, JUNK_LIMIT)

    stats["elapsed"] = round(time.time() - t0, 2)
    stats["root"] = root
    return root_node, {
        "largest": largest,
        "stale": stale,
        "duplicates": dups,
        "junk": junk,
        "stats": stats,
    }


def _rollup(node: Node) -> int:
    """Post-order size aggregation, iterative to stay stack-safe."""
    stack = [(node, False)]
    while stack:
        cur, done = stack.pop()
        if done:
            total = 0
            count = 0
            for c in cur.children:
                total += c.size
                count += c.count
            cur.size = total
            cur.count = count
            continue
        stack.append((cur, True))
        for c in cur.children:
            if c.is_dir:
                stack.append((c, False))
    return node.size


def _walk_files(node: Node, path=""):
    """Yield (relpath, node, mtime) for every file under *node*."""
    root_name = node.name
    stack = [(node, "")]
    while stack:
        cur, rel = stack.pop()
        if not cur.is_dir:
            yield rel, cur, cur.mtime
            continue
        for c in cur.children:
            child_rel = c.name if not rel else rel + os.sep + c.name
            if c.is_dir:
                stack.append((c, child_rel))
            else:
                yield child_rel, c, c.mtime


def _largest_files(root: Node, limit: int):
    items = []
    base = root.name
    for rel, n, mtime in _walk_files(root):
        if n.size:
            items.append(
                {
                    "path": os.path.join(base, rel) if rel else base,
                    "size": n.size,
                    "mtime": mtime,
                    "ext": n.ext,
                }
            )
    items.sort(key=lambda x: -x["size"])
    return items[:limit]


def _stale_files(root: Node, min_size: int, days: int, limit: int):
    cutoff = time.time() - days * 86400
    base = root.name
    out = []
    for rel, n, mtime in _walk_files(root):
        if n.size >= min_size and mtime and mtime < cutoff:
            out.append(
                {
                    "path": os.path.join(base, rel) if rel else base,
                    "size": n.size,
                    "mtime": mtime,
                    "days": int((time.time() - mtime) // 86400),
                    "ext": n.ext,
                }
            )
    out.sort(key=lambda x: -x["size"])
    return out[:limit]


def _hash_head(path: str, chunk=256 * 1024) -> str:
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        h.update(f.read(chunk))
    return h.hexdigest()


def _hash_full(path: str) -> str:
    h = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as f:
        while True:
            b = f.read(1024 * 1024)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def _duplicates(by_size, limit, progress=True):
    """Two-tier hashing: cheap head hash prunes, full hash confirms."""
    groups = []
    candidates = {s: paths for s, paths in by_size.items() if len(paths) > 1}
    if not candidates:
        return groups

    total = len(candidates)
    try:
        _dedupe(candidates, groups, limit, total, progress)
    finally:
        if progress and total >= 20:
            # Wipe the in-place progress line so it never smears into the output.
            sys.stderr.write("\r" + " " * 46 + "\r")
            sys.stderr.flush()
    return groups


def _dedupe(candidates, groups, limit, total, progress):
    for i, (size, paths) in enumerate(sorted(candidates.items(), reverse=True)):
        if progress and i % 20 == 0:
            sys.stderr.write(f"\r  hashing  {i}/{total} size groups   ")
            sys.stderr.flush()
        if len(groups) >= limit:
            break
        try:
            heads: dict[str, list] = {}
            for p, name in paths:
                heads.setdefault(_hash_head(p), []).append((p, name))
            for _, same in heads.items():
                if len(same) < 2:
                    continue
                full: dict[str, list] = {}
                for p, name in same:
                    full.setdefault(_hash_full(p), []).append((p, name))
                for _, dup in full.items():
                    if len(dup) >= 2:
                        groups.append(
                            {
                                "size": size,
                                "count": len(dup),
                                "wasted": size * (len(dup) - 1),
                                "files": [{"path": p, "name": n} for p, n in dup],
                            }
                        )
        except OSError:
            continue

    if progress:
        sys.stderr.write("\r" + " " * 60 + "\r")
        sys.stderr.flush()
    groups.sort(key=lambda g: -g["wasted"])
    return groups[:limit]


def _junk_dirs(root_node: Node, limit):
    """Regenerable directories, deepest-labelled, biggest first.

    Reports the top-most junk directory of each chain (`target/` not every class
    folder inside it): that is the thing you actually delete.
    """
    out = []
    stack = [(root_node, "")]
    while stack:
        cur, path = stack.pop()
        for c in cur.children:
            if not c.is_dir:
                continue
            p = f"{path}/{c.name}" if path else c.name
            if c.junk:
                out.append({"kind": c.junk, "size": c.size, "count": c.count,
                            "path": p, "name": c.name})
                continue          # do not report nested junk separately
            stack.append((c, p))
    out.sort(key=lambda d: -d["size"])
    return out[:limit]


def to_json(node: Node, depth=CHILD_LIMIT, max_nodes=NODE_BUDGET):
    """Serialise the tree, keeping only the biggest *depth* children per folder.

    A full tree of a real disk is far larger than any page should carry, and
    far less useful: the thousands of 3 KB files never decide where the space
    went. So each folder keeps its biggest children and folds the tail into one
    aggregate block.

    The per-folder limit alone still explodes on a whole drive (80 children at
    every level), so the result is also capped by a global node budget. The
    deepest layout that fits is used, which keeps detail near the top of the
    tree - exactly where a human is looking.
    """
    best = None
    for d in range(depth, 0, -1):
        try:
            out, count = _to_json(node, d, max_nodes)
        except _TooBig:
            # Aborted early, so this failed attempt stays cheap.
            continue
        best = out
        break
    if best is None:  # pathological: even a top-level-only tree is too big
        best = _to_json(node, 1, 10 ** 9)[0]
    return best


class _TooBig(Exception):
    pass


def _to_json(node: Node, depth: int, budget: int):
    """One pass. Returns (payload, node count); aborts once *budget* is blown."""
    # k = file count at or below this node, j = junk kind. Both are what make
    # "two folders, same size, wildly different nature" visible.
    out = {"n": node.name, "s": node.size, "k": node.count}
    if node.junk:
        out["j"] = node.junk
    if not node.is_dir:
        out["m"] = int(node.mtime) if node.mtime else 0
        if node.ext:
            out["e"] = node.ext
        return out, 1

    kids = sorted(node.children, key=lambda c: -c.size)
    keep = [c for c in kids if c.size > 0][:depth] if depth > 1 else []
    rest = kids[len(keep):]
    count = 1
    if keep:
        children = []
        for c in keep:
            sub, n = _to_json(c, depth - 1, budget - count)
            children.append(sub)
            count += n
            if count > budget:
                raise _TooBig
        out["c"] = children
    if rest:
        hidden = sum(c.size for c in rest)
        out["h"] = {"n": f"+{len(rest):,} 更多", "s": hidden, "count": len(rest),
                    "k": sum(c.count for c in rest)}
    return out, count
