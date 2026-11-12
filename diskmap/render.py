"""Offline renderer: paint the same map with PIL.

Two jobs:
  * export a PNG poster (shareable, no browser needed)
  * drive the animated video, where every frame is a map at some zoom depth

Layout is a "title-bar treemap": every folder reserves a dark strip for its own
name before subdividing the remaining area. Labels therefore never collide with
the rectangles they describe - the single biggest readability win over a plain
squarified map.
"""

from __future__ import annotations

import os

from PIL import Image, ImageDraw, ImageFont

FONT_DIR = r"C:\Windows\Fonts"
FONT_CANDIDATES = {
    "bold": ["msyhbd.ttc", "simhei.ttf", "Dengb.ttf"],
    "regular": ["msyh.ttc", "simsun.ttc", "Deng.ttf"],
    "mono": ["consola.ttf", "cour.ttf"],
}

# One consistent palette with the HTML report so screenshots and page agree.
CAT_COLOR = {
    "video": (244, 114, 182),
    "image": (167, 139, 250),
    "audio": (251, 191, 36),
    "archive": (251, 146, 60),
    "code": (94, 234, 212),
    "doc": (96, 165, 250),
    "app": (248, 113, 113),
    "other": (100, 116, 139),
}

PALETTE = {
    "video": "mp4 mkv avi mov wmv flv webm m4v ts mpg".split(),
    "image": "png jpg jpeg gif bmp webp svg ico psd raw heic tif tiff".split(),
    "audio": "mp3 wav flac aac ogg m4a wma".split(),
    "archive": "zip rar 7z tar gz bz2 xz iso cab".split(),
    "code": "js ts jsx tsx py java go rs c cpp h cs rb php kt swift sh sql".split(),
    "doc": "pdf doc docx xls xlsx ppt pptx txt md csv json xml yaml yml log epub".split(),
    "app": "exe dll msi so dylib bin jar apk app sys lib o obj pdb".split(),
}
EXT2CAT = {e: c for c, exts in PALETTE.items() for e in exts}

BG = (11, 13, 18)
INK = (232, 236, 244)
DIM = (139, 147, 167)

_font_cache: dict[tuple[int, str], ImageFont.FreeTypeFont] = {}


def font(size: int, weight: str = "regular"):
    key = (max(6, int(size)), weight)
    if key in _font_cache:
        return _font_cache[key]
    f = None
    for name in FONT_CANDIDATES[weight]:
        path = os.path.join(FONT_DIR, name)
        if os.path.exists(path):
            try:
                f = ImageFont.truetype(path, key[0])
                break
            except OSError:
                continue
    if f is None:
        f = ImageFont.load_default()
    _font_cache[key] = f
    return f


def human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


# ---------------------------------------------------------------- squarify
def squarify(items, x, y, w, h):
    """Squarified treemap. items: [(size, payload)] with positive sizes."""
    total = sum(s for s, _ in items)
    out = []
    if total <= 0 or w <= 0 or h <= 0:
        return out
    scale = (w * h) / total
    areas = [(s * scale, p) for s, p in items if s > 0]
    i, cx, cy, cw, ch = 0, x, y, w, h
    while i < len(areas) and cw > 0.5 and ch > 0.5:
        side = min(cw, ch)
        row, row_sum, best, j = [], 0.0, float("inf"), i
        while j < len(areas):
            a = areas[j][0]
            s = row_sum + a
            vals = [r[0] for r in row] + [a]
            worst = _worst_ratio(s, vals, side)
            if not row or worst <= best:
                row.append(areas[j])
                row_sum = s
                best = worst
                j += 1
            else:
                break
        if cw >= ch:
            sw = row_sum / ch
            py = cy
            for a, p in row:
                ih = a / sw
                out.append((cx, py, sw, ih, p))
                py += ih
            cx += sw
            cw -= sw
        else:
            sh = row_sum / cw
            px = cx
            for a, p in row:
                iw = a / sh
                out.append((px, cy, iw, sh, p))
                px += iw
            cy += sh
            ch -= sh
        i = j
    return out


def _worst_ratio(s, arr, side):
    if s <= 0:
        return float("inf")
    mx, mn = max(arr), max(min(arr), 1e-9)
    s2, w2 = s * s, side * side
    return max((w2 * mx) / s2, s2 / (w2 * mn))


def _tint(rgb, k):
    return tuple(min(255, max(0, int(v * k))) for v in rgb)


def _blend(rgb, bg, alpha):
    return tuple(int(a * alpha + b * (1 - alpha)) for a, b in zip(rgb, bg))


def decorate(node: dict, _depth=0) -> dict:
    """Annotate every folder with the category that dominates its bytes.

    Without this every top-level box is grey, which throws away the single
    most useful signal in the picture: what kind of data ate the disk.
    """
    if not node.get("c"):
        node["_cat"] = EXT2CAT.get(node.get("e", ""), "other")
        return node
    tally: dict[str, int] = {}
    for c in node["c"]:
        decorate(c, _depth + 1)
        tally[c["_cat"]] = tally.get(c["_cat"], 0) + c.get("s", 0)
    if node.get("h"):
        tally["other"] = tally.get("other", 0) + node["h"]["s"]
    if tally:
        dom, val = max(tally.items(), key=lambda kv: kv[1])
        total = sum(tally.values()) or 1
        # Only claim a category when it really dominates, else stay neutral.
        node["_cat"] = dom if val / total >= 0.30 else "other"
    else:
        node["_cat"] = "other"
    return node


def cat_of(node: dict) -> str:
    return node.get("_cat") or EXT2CAT.get(node.get("e", ""), "other")


# Depth shading: deeper means slightly calmer, so nesting reads as depth
# without swallowing the category hue.
DEPTH_K = [1.00, 0.93, 0.86, 0.80, 0.76, 0.73, 0.71]


def _depth_k(depth: int) -> float:
    return DEPTH_K[min(depth, len(DEPTH_K) - 1)]


def _hatch(d: ImageDraw.ImageDraw, box, ink, step=13):
    """Diagonal texture for blocks made of thousands of tiny files.

    A flat rectangle that is 200 MB of 3 KB files looks identical to an empty
    folder. The hatch is the visual shorthand for "no single file matters here".
    """
    x, y, w, h = box
    if w < 12 or h < 12:
        return
    x1, y1, x2, y2 = x + 2, y + 2, x + w - 2, y + h - 2
    if x2 <= x1 or y2 <= y1:
        return
    # 45-degree lines running down-left; clip each one to the box, otherwise
    # tails spill into neighbouring rectangles and draw stray X shapes.
    for i in range(int((x2 - x1 + y2 - y1) / step) + 2):
        cx = x1 + i * step              # x where the line crosses y1
        ax, ay = cx, y1                 # start where the line crosses the top
        bx, by = cx - (y2 - y1), y2     # would end at the bottom edge
        if bx < x1:                     # leaves through the left edge first
            bx, by = x1, ay + (ax - x1)
        if ax > x2:                     # enters through the right edge
            ax, ay = x2, ay + (ax - x2)
        if ax <= bx:
            continue
        d.line([ax, ay, bx, by], fill=ink, width=1)


def draw_map(img, node, box, *, depth=1, max_depth=4, highlight=None, bg=BG,
             label_scale=1.0, min_label_w=52, min_label_h=20):
    x, y, w, h = box
    d = ImageDraw.Draw(img, "RGBA")
    kids = [c for c in node.get("c", []) if c.get("s", 0) > 0]
    if node.get("h"):
        kids.append({"n": f"… {node['h']['count']} 个小项", "s": node["h"]["s"], "_agg": True})
    kids.sort(key=lambda c: -c["s"])
    if not kids:
        return

    # A folder whose single child fills it adds no information - skip its bar.
    trivial = len(kids) == 1 and kids[0]["s"] >= node.get("s", 0) * 0.995
    body = box
    if not trivial and w > 74 and h > 34:
        band = max(13, min(int(21 * label_scale), int(h * 0.22)))
        d.rectangle([x, y, x + w, y + band], fill=(20, 24, 33, 255))
        d.line([x, y + band - 1, x + w, y + band - 1], fill=(45, 52, 68, 255))
        fs = max(9, min(int(band * 0.72), int(15 * label_scale)))
        name = _fit(d, node.get("n", ""), fs, w - 14, bold=True)
        d.text((x + 7, y + (band - fs) * 0.45), name, font=font(fs, "bold"), fill=INK)
        body = (x, y + band, w, h - band)

    bx, by, bw, bh = body
    if bw <= 0 or bh <= 0:
        return

    gap = 1 if depth <= 2 else 0
    total = sum(c["s"] for c in kids) or 1
    for rx, ry, rw, rh, child in squarify([(c["s"], c) for c in kids], bx, by, bw, bh):
        if rw < 1.2 or rh < 1.2:
            continue
        g = gap if (rw > 2 * gap + 1 and rh > 2 * gap + 1) else 0
        cat = cat_of(child)
        base = (70, 78, 95) if child.get("_agg") else CAT_COLOR.get(cat, CAT_COLOR["other"])
        col = _tint(base, _depth_k(depth))
        if highlight and child.get("n") == highlight:
            col = _tint(col, 1.45)
        d.rectangle([rx + g, ry + g, rx + rw - g, ry + rh - g], fill=col)
        if highlight and child.get("n") == highlight:
            d.rectangle([rx + 1, ry + 1, rx + rw - 1, ry + rh - 1],
                        outline=(255, 255, 255), width=2)

        inner = (rx + g, ry + g, max(1, rw - g * 2), max(1, rh - g * 2))
        if child.get("c") and depth < max_depth and rw > 64 and rh > 46:
            draw_map(img, child, inner, depth=depth + 1, max_depth=max_depth,
                     label_scale=label_scale, min_label_w=min_label_w,
                     min_label_h=min_label_h, bg=bg)
        else:
            if child.get("c") or child.get("_agg"):
                # Shut folder or a bucket of hundreds of siblings: the texture
                # says "this is a pile, not a file" so it never reads as a hole.
                _hatch(d, (rx + g, ry + g, rw - g * 2, rh - g * 2),
                       (255, 255, 255, 60))
            if rw >= min_label_w and rh >= min_label_h:
                _leaf_label(d, child, inner, total, label_scale)
    return img


def _leaf_label(d, node, box, total, label_scale):
    x, y, w, h = box
    fs = max(9, min(int(13 * label_scale), int(w / 6.0), int(h / 2.6)))
    name = _fit(d, node["n"], fs, w - 10, bold=True)
    d.text((x + 5, y + 4), name, font=font(fs, "bold"), fill=INK)
    if h > fs * 2.9 and w > 62:
        pct = node["s"] / total * 100
        sub = human(node["s"]) if pct > 0.05 else ""
        if sub:
            d.text((x + 5, y + 5 + fs), sub, font=font(max(8, fs - 2)), fill=DIM)


def _fit(d, text, size, maxw, bold=False):
    f = font(size, "bold" if bold else "regular")
    if d.textlength(text, font=f) <= maxw:
        return text
    while text and d.textlength(text + "…", font=f) > maxw:
        text = text[:-1]
    return text + "…" if text else ""


# ---------------------------------------------------------------- poster
def render_poster(tree, out_path, w=2400, h=1500, title="", subtitle="",
                  bg=BG, max_depth=4, footer=""):
    """A share-ready PNG: title bar, map, legend, footer."""
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img, "RGBA")

    head_h = int(h * 0.115)
    foot_h = int(h * 0.055)
    pad = int(w * 0.018)

    if title:
        d.text((pad, int(head_h * 0.18)), title, font=font(int(h * 0.040), "bold"), fill=INK)
    if subtitle:
        d.text((pad, int(head_h * 0.60)), subtitle, font=font(int(h * 0.019)), fill=DIM)

    box = (pad, head_h, w - pad * 2, h - head_h - foot_h)
    d.rectangle([box[0], box[1], box[0] + box[2], box[1] + box[3]], fill=(16, 19, 26))
    draw_map(img, tree, box, depth=1, max_depth=max_depth,
             label_scale=w / 1600, bg=bg)

    ly = h - foot_h + int(foot_h * 0.30)
    lx = pad
    labels = {"video": "视频", "image": "图片", "audio": "音频", "archive": "压缩包",
              "code": "代码", "doc": "文档", "app": "程序", "other": "其他"}
    fs = int(h * 0.0155)
    f = font(fs)
    sq = int(h * 0.012)
    for cat, name in labels.items():
        d.rectangle([lx, ly + 1, lx + sq, ly + 1 + sq], fill=CAT_COLOR[cat])
        d.text((lx + sq + 7, ly - 1), name, font=f, fill=DIM)
        lx += sq + 7 + d.textlength(name, font=f) + int(w * 0.013)

    if footer:
        fw = d.textlength(footer, font=f)
        d.text((w - pad - fw, ly - 1), footer, font=f, fill=(90, 98, 116))

    img.save(out_path, "PNG", optimize=True)
    return out_path
