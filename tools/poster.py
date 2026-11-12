"""Dev harness: render a poster from a path in one line."""

import sys

sys.path.insert(0, r"D:\Github-code\diskmap")

from diskmap.render import decorate, render_poster
from diskmap.scan import _human, scan, to_json

path = sys.argv[1] if len(sys.argv) > 1 else r"D:\Github-code"
out = sys.argv[2] if len(sys.argv) > 2 else r"D:\Github-code\diskmap\out\poster2.png"
depth = int(sys.argv[3]) if len(sys.argv) > 3 else 40

root, extra = scan(path, progress=False)
tree = decorate(to_json(root, depth=depth))
render_poster(
    tree,
    out,
    2400,
    1500,
    title="DiskMap",
    subtitle=f"{_human(root.size)}  ·  {extra['stats']['files']:,} files",
    footer=path,
)
print("wrote", out, _human(root.size))
