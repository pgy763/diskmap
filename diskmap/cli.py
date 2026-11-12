"""CLI entry point: scan a path, write the report, print the top offenders."""

from __future__ import annotations

import argparse
import os
import sys
import webbrowser

from .report import write_report
from .scan import DEFAULT_EXCLUDES, _human, scan


def _bar(frac: float, width: int = 22) -> str:
    n = max(1, int(round(frac * width)))
    return "█" * n + "░" * (width - n)


def main(argv=None):
    # Windows consoles default to GBK, which cannot encode the bars below.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        prog="diskmap",
        description="Scan a folder and build a single-file, offline disk map.",
    )
    ap.add_argument("path", nargs="?", default=".", help="要扫描的目录（默认当前目录）")
    ap.add_argument("-o", "--out", default=None, help="输出 HTML 路径")
    ap.add_argument(
        "--exclude", action="append", default=None,
        help="额外排除的目录名，可重复，如 --exclude node_modules",
    )
    ap.add_argument("--all", action="store_true", help="不排除任何目录（更慢、更大）")
    ap.add_argument("--no-open", action="store_true", help="生成后不自动打开浏览器")
    ap.add_argument("--quiet", action="store_true", help="不打印扫描进度")
    args = ap.parse_args(argv)

    target = os.path.abspath(args.path)
    if not os.path.isdir(target):
        print(f"不是目录: {target}", file=sys.stderr)
        return 2

    excludes = set() if args.all else set(DEFAULT_EXCLUDES)
    if args.exclude:
        excludes |= set(args.exclude)

    print(f"\n  扫描  {target}")
    print(f"  排除  {', '.join(sorted(excludes)) or '(无)'}\n")

    # A carriage-return progress line written to a pipe turns into garbage, so
    # only animate when a terminal is actually watching.
    animate = (not args.quiet) and sys.stderr.isatty()
    root, extra = scan(target, excludes=excludes, progress=animate)
    stats = extra["stats"]

    total = stats["bytes"] or 1
    print(f"  {'─' * 62}")
    print(f"  {_human(total):>10}   {stats['files']:,} 个文件   "
          f"{stats['dirs']:,} 个目录   {stats['elapsed']}s")
    if stats["errors"]:
        print(f"  {stats['errors']} 个目录读不了（权限）")
    print(f"  {'─' * 62}\n")

    print("  空间去哪了")
    kids = sorted(root.children, key=lambda c: -c.size)[:8]
    for c in kids:
        frac = c.size / total
        print(f"  {_bar(frac)} {frac * 100:5.1f}%  {_human(c.size):>9}  {c.name}")

    dups = extra["duplicates"]
    if dups:
        wasted = sum(g["wasted"] for g in dups)
        print(f"\n  重复文件  {len(dups)} 组，可释放 {_human(wasted)}")
        for g in dups[:3]:
            print(f"    {g['count']}× {_human(g['size']):>9}  {g['files'][0]['name'][:52]}")
        if len(dups) > 3:
            print(f"    … 另外 {len(dups) - 3} 组")

    stale = extra["stale"]
    if stale:
        print(f"\n  一年没动  {len(stale)} 个文件，共 {_human(sum(s['size'] for s in stale))}")
        for s in stale[:3]:
            print(f"    {_human(s['size']):>9}  {s['days']:>4} 天  {s['path'][-56:]}")

    out = args.out or os.path.join(
        os.getcwd(), f"diskmap-{os.path.basename(target) or 'root'}.html"
    )
    size = write_report(root, extra, out, title=f"DiskMap · {target}")
    print(f"\n  报告  {out}   ({size / 1024:.0f} KB)")

    if not args.no_open:
        try:
            webbrowser.open("file:///" + out.replace("\\", "/"))
        except Exception:
            pass
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
