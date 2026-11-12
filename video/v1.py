"""Video 1 - "C 盘解剖": a 40 s vertical short that turns a whole drive into a map.

Structure (this is a short-form video, so the hook is the first 1.5 s and every
scene must land a number):

  0.0 - 2.2   hook     214GB, but you can't name what's in it
  2.2 - 7.0   the bar  one continuous 214GB bar, filled by the top-level dirs
  7.0 - 21.0  the map  treemap grows block by block; file counter rolls up
 21.0 - 29.0  zoom     into Users (134.6GB) and then deeper
 29.0 - 36.0  findings duplicates 12.8GB + dead files 16.5GB
 36.0 - 41.0  card     one HTML file, no install

Every spatial transition is a real 2-D crop of the same treemap, not a
recomputed layout, so the eye keeps its bearings across cuts.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw, ImageFilter  # noqa: E402

from diskmap.render import CAT_COLOR, human, squarify  # noqa: E402
from video.kit import (  # noqa: E402
    ACCENT, BAD, BLUE, DIM, FAINT, INK, PINK, WARN,
    Video, background, clamp, ease_in_out, ease_out, ease_out_back,
    ease_out_expo, font, glow_text, lerp, mix, norm, rrect, run, scene,
    text, vignette, wrap, measure, fmt_int,
)

W, H = 1080, 1920
FPS = 30
DUR = 41.0

M = 72                      # safe margin
MAP_BOX = (M, 440, W - 2 * M, 700)   # x, y, w, h
MAP_AREA = MAP_BOX[2] * MAP_BOX[3]


# ------------------------------------------------------------------ data
# Taken from `python -m diskmap.cli C:/` on the real machine, and hard-coded so
# the video is reproducible without re-scanning a 214 GB drive for every render.
DRIVE = {
    "n": "C:", "s": 214.0 * 1024 ** 3,
    "c": [
        {"n": "Users", "s": 134.6, "c": [
            {"n": "lenovo", "s": 118.0, "c": [
                {"n": "AppData", "s": 61.2, "e": ""},
                {"n": ".cache", "s": 14.4, "e": ""},
                {"n": "Downloads", "s": 11.8, "e": ""},
                {"n": "Documents", "s": 9.6, "e": ""},
                {"n": "Pictures", "s": 7.4, "e": ""},
                {"n": "Videos", "s": 5.1, "e": ""},
                {"n": "Desktop", "s": 3.2, "e": ""},
                {"n": "其他", "s": 5.3, "e": ""},
            ]},
            {"n": "Public", "s": 8.4, "e": ""},
            {"n": "其他", "s": 8.2, "e": ""},
        ]},
        {"n": "Windows", "s": 43.5, "c": [
            {"n": "WinSxS", "s": 14.2, "e": ""},
            {"n": "System32", "s": 11.3, "e": ""},
            {"n": "Installer", "s": 6.1, "e": ""},
            {"n": "assembly", "s": 3.4, "e": ""},
            {"n": "servicing", "s": 2.8, "e": ""},
            {"n": "其他", "s": 5.7, "e": ""},
        ]},
        {"n": "Program Files (x86)", "s": 14.4, "e": ""},
        {"n": "Program Files", "s": 9.7, "e": ""},
        {"n": "hiberfil.sys", "s": 6.3, "e": "sys"},
        {"n": "ProgramData", "s": 5.2, "e": ""},
        {"n": "swapfile.sys", "s": 0.25, "e": "sys"},
    ],
}
def _to_bytes(node, depth=0):
    """Sizes are written in GB for readability; convert the whole tree once."""
    node["s"] = float(node["s"]) * 1024 ** 3 if depth else node["s"]
    for c in node.get("c", []):
        _to_bytes(c, depth + 1)
    return node


CAT_HINT = {
    "AppData": "other", ".cache": "other", "Downloads": "archive",
    "Pictures": "image", "Videos": "video", "Documents": "doc",
    "WinSxS": "app", "System32": "app", "Installer": "archive",
    "assembly": "app", "servicing": "archive", "Public": "other",
}


def _paint(node):
    if node["n"].lower().endswith(".sys"):
        node["_cat"] = "app"
    else:
        node["_cat"] = CAT_HINT.get(node["n"], "other")
    for c in node.get("c", []):
        _paint(c)


_to_bytes(DRIVE)
_paint(DRIVE)
TOTAL = DRIVE["s"]


# ------------------------------------------------------------------ treemap
def _hatch(d, box, alpha=40, step=14):
    """Diagonal texture, clipped per line so it never spills into a neighbour."""
    x, y, w, h = box
    x1, y1, x2, y2 = int(x + 2), int(y + 2), int(x + w - 2), int(y + h - 2)
    if x2 - x1 < 10 or y2 - y1 < 10 or alpha <= 2:
        return
    ink = (255, 255, 255, alpha)
    for i in range(int((x2 - x1 + y2 - y1) / step) + 2):
        ax = x1 + i * step
        ay = y1
        bx = ax - (y2 - y1)
        by = y2
        if bx < x1:
            bx, by = x1, ay + (ax - x1)
        if ax > x2:
            ax, ay = x2, ay + (ax - x2)
        if ax > bx:
            d.line([ax, ay, bx, by], fill=ink, width=1)


def draw_map_anim(img, node, box, *, depth=1, max_depth=3, p=1.0,
                  band=True, dim=None, delay=(0.0, 0.30, 0.60), span=0.55):
    """Recursive squarified map with a staged reveal.

    Children are drawn *inside* their parent's rectangle, so the nesting is
    always visible; the parent's own fill stays as the framing colour. Depth
    decides when a level appears, which makes the map read as "growing" from
    the top of the tree downwards instead of popping in all at once.
    """
    d = ImageDraw.Draw(img, "RGBA")
    x, y, w, h = box
    kids = [c for c in node.get("c", []) if c["s"] > 0]
    if not kids:
        return

    body = (x, y, w, h)
    if band and depth <= 2:
        # A band per level, not just at the root: without it a folder that is
        # mostly one child silently hands its area to that child, and the map
        # stops showing where you are in the tree.
        bh = 46 if depth == 1 else 36
        if h > bh * 2.2 and w > bh * 3.4:
            d.rectangle([x, y, x + w, y + bh], fill=(17, 20, 28, 255))
            fs = 26 if depth == 1 else 20
            name = _fit_name(d, node["n"], fs, w - 24)
            d.text((x + 12, y + bh / 2 - fs * 0.75), name, font=font(fs, "bold"),
                   fill=(232, 236, 244))
            body = (x, y + bh, w, h - bh)

    total = sum(c["s"] for c in kids) or 1
    for rx, ry, rw, rh, child in squarify([(c["s"], c) for c in kids], *body):
        if rw < 1 or rh < 1:
            continue
        local = clamp((p - delay[min(depth - 1, len(delay) - 1)]) / span)
        if local <= 0:
            continue
        e = ease_out(local) if local < 1 else 1.0
        sx, sy = rx + rw / 2, ry + rh / 2
        gx, gy = rw * (0.06 * (1 - e)), rh * (0.06 * (1 - e))
        box2 = (sx - rw / 2 + gx, sy - rh / 2 + gy, rw - 2 * gx, rh - 2 * gy)
        a = int(255 * clamp(local * 2.2))
        base = CAT_COLOR.get(child.get("_cat", "other"), CAT_COLOR["other"])
        k = [1.0, 0.90, 0.82][min(depth - 1, 2)]
        col = tuple(int(v * k) for v in base)
        if dim is not None and child is not dim:
            col = mix(col, (22, 26, 35), 0.70)
        d.rectangle([box2[0], box2[1], box2[0] + box2[2], box2[1] + box2[3]],
                    fill=col + (a,), outline=(255, 255, 255, int(a * 0.09)))
        if not child.get("c") and box2[2] * box2[3] > 0.05 * MAP_AREA:
            # A big single block with no children is still a pile of thousands
            # of files; hatching it keeps it from reading as empty space, which
            # is exactly the rule the real report uses.
            _hatch(d, box2, int(a * 0.16))
        if child.get("c") and depth < max_depth and box2[2] > 70 and box2[3] > 60:
            draw_map_anim(img, child, box2, depth=depth + 1, max_depth=max_depth,
                          p=p, band=band, dim=dim, delay=delay, span=span)
        elif box2[2] > 96 and box2[3] > 56 and local > 0.7:
            la = clamp((local - 0.7) / 0.3)
            fs = 24 if depth == 1 else 21
            name = _fit_name(d, child["n"], fs, box2[2] - 20)
            d.text((box2[0] + 10, box2[1] + 8), name, font=font(fs, "bold"),
                   fill=(255, 255, 255, int(240 * la)))
            if box2[3] > 92:
                d.text((box2[0] + 10, box2[1] + 12 + fs), human(child["s"]),
                       font=font(fs - 6), fill=(255, 255, 255, int(150 * la)))


def _fit_name(d, s, size, maxw):
    f = font(size, "bold")
    if d.textlength(s, font=f) <= maxw:
        return s
    while s and d.textlength(s + "…", font=f) > maxw:
        s = s[:-1]
    return s + "…" if s else ""


# ------------------------------------------------------------------ scenes
def scene_hook(t, lt):
    """A single number, and the uncomfortable question."""
    img = background(W, H)
    d = ImageDraw.Draw(img)
    p = norm(t, 0, 2.2)
    a = clamp(ease_out(norm(t, 0, 0.35)))

    # Everything lives between y=270 and y=1200: the bottom 35% of a vertical
    # feed frame is covered by the caption, the username row and the action
    # buttons, so a hook that lands there is a hook nobody reads.
    cy = 690
    glow_text(img, (W / 2 - measure("214 GB", 190, "bold") / 2, cy),
              "214 GB", 190, (255, 255, 255), "bold")
    d = ImageDraw.Draw(img)
    text(d, (W / 2, cy + 240), "这是你 C 盘的体积", 40, DIM, anchor="ma")

    if p > 0.45:
        q = ease_out(norm(t, 1.0, 2.0))
        text(d, (W / 2, 1120 + (1 - q) * 30),
             "你能说出里面装了什么吗？", 52, (255, 255, 255), weight="bold", anchor="ma")

    return vignette(img, 0.5) if a > 0.5 else img


def _bar_segments(min_pct=1.0):
    """Top-level slices, with sub-1% entries merged.

    swapfile.sys is 0.25 GB of 214 GB - 1.2 px at this width. Drawn on its own it
    reads as a stray line, so fold the tail into one "其他" slice and keep the
    bar honest about what the reader can actually see.
    """
    big = [c for c in DRIVE["c"] if c["s"] / TOTAL * 100 >= min_pct]
    small = [c for c in DRIVE["c"] if c["s"] / TOTAL * 100 < min_pct]
    out = [dict(c) for c in big]
    if small:
        out.append({"n": "其他", "s": sum(c["s"] for c in small), "_cat": "other"})
    return out


def scene_bar(t, lt):
    """One bar, split by top-level folder. The simplest possible mental model."""
    img = background(W, H)
    d = ImageDraw.Draw(img)

    head = ease_out(norm(lt, 0, 0.5))
    text(d, (M, 300 - (1 - head) * 20), "C:\\  ·  214.0GB", 40, DIM, weight="bold")

    bx, by, bw, bh = M, 360, W - 2 * M, 104
    d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=14, fill=(24, 28, 38))

    p = norm(lt, 0.3, 3.2)
    x = bx
    kids = _bar_segments()
    # Paint the segments on their own layer and clip with the track's rounded
    # outline: rounding each segment separately leaves notches at every boundary
    # and lets the last one poke past the track's corner.
    layer = Image.new("RGB", (W, H), (24, 28, 38))
    ld = ImageDraw.Draw(layer)
    for i, c in enumerate(kids):
        seg = bw * (c["s"] / TOTAL)
        local = clamp((p - i * 0.06) / 0.5)
        if local <= 0:
            break
        wseg = seg * ease_out(local)
        col = CAT_COLOR.get(c["_cat"], CAT_COLOR["other"])
        ld.rectangle([x, by, x + wseg, by + bh], fill=col)
        if seg > 120 and local > 0.9:
            name = c["n"]
            while measure(name, 24, "bold") > seg - 20 and len(name) > 3:
                name = name[:-1]
            ld.text((x + 10, by + bh / 2 - 16), name, font=font(24, "bold"),
                    fill=(20, 24, 32))
        x += seg

    mask = Image.new("L", (W, H), 0)
    ImageDraw.Draw(mask).rounded_rectangle([bx, by, bx + bw, by + bh], radius=14, fill=255)
    img.paste(layer, (0, 0), mask)

    # Legend list. Its own clock: tying it to `p` (which finishes at 3.2 s)
    # meant rows 4-5 never cleared their delay, so the list stopped at two.
    y = 560
    rows = sorted(kids, key=lambda k: -k["s"])[:5]
    for i, c in enumerate(rows):
        local = clamp(norm(lt, 0.8 + i * 0.28, 1.5 + i * 0.28))
        if local <= 0:
            break
        e = ease_out(local)
        yy = y + i * 106
        col = CAT_COLOR.get(c["_cat"], CAT_COLOR["other"])
        d.rounded_rectangle([M, yy + (1 - e) * 24, M + 8, yy + 50 + (1 - e) * 24],
                            radius=4, fill=col + (int(255 * e),))
        text(d, (M + 34, yy + (1 - e) * 24), c["n"], 42, (255, 255, 255, int(240 * e)),
             weight="bold")
        pct = c["s"] / TOTAL * 100
        text(d, (W - M, yy + (1 - e) * 24), f"{pct:.1f}%", 42,
             (255, 255, 255, int(200 * e)), weight="bold", anchor="ra")
        text(d, (W - M, yy + 50 + (1 - e) * 24), human(c["s"]), 28,
             (DIM[0], DIM[1], DIM[2], int(220 * e)), anchor="ra")

    text(d, (M, 1116), "资源管理器只按名字排序", 30, DIM)
    if lt > 1.6:
        a = clamp(norm(lt, 1.6, 2.4))
        text(d, (M, 1166), "从来不告诉你谁在偷空间", 30,
             mix(DIM, (255, 255, 255), a))
    return img


def scene_map(t, lt):
    """The payoff: the map grows and the file counter rolls up."""
    img = background(W, H)
    d = ImageDraw.Draw(img)

    p = norm(lt, 0.15, 6.4)
    d.rounded_rectangle([MAP_BOX[0] - 4, MAP_BOX[1] - 4,
                         MAP_BOX[0] + MAP_BOX[2] + 4, MAP_BOX[1] + MAP_BOX[3] + 4],
                        radius=10, outline=(255, 255, 255, 30), width=2)
    draw_map_anim(img, DRIVE, MAP_BOX, max_depth=3, p=p)

    d = ImageDraw.Draw(img)
    cnt = int(764363 * ease_out(norm(lt, 0.4, 5.6)))
    text(d, (M, 284), "C:", 46, (255, 255, 255), weight="bold")
    text(d, (M, 350), fmt_int(cnt) + " 个文件", 44, ACCENT, weight="bold")
    text(d, (W - M, 350), "214.0GB", 44, DIM, weight="bold", anchor="ra")

    cap_a = clamp(norm(lt, 3.2, 4.0))
    if cap_a > 0:
        text(d, (M, 1180), "面积 = 体积    颜色 = 类型", 40,
             (255, 255, 255, int(255 * cap_a)), weight="bold")
    cap_b = clamp(norm(lt, 4.6, 5.4))
    if cap_b > 0:
        text(d, (M, 1240), "764,363 个文件，一屏看完", 38,
             (DIM[0], DIM[1], DIM[2], int(255 * cap_b)))
    return img


def scene_zoom(t, lt):
    """Cut into Users, then into lenovo. Same map, deeper crops."""
    img = background(W, H)
    d = ImageDraw.Draw(img)

    p = norm(lt, 0, 3.0)
    if p <= 0.52:
        users = next(c for c in DRIVE["c"] if c["n"] == "Users")
        k = ease_in_out(clamp(p / 0.5))
        draw_map_anim(img, DRIVE, MAP_BOX, max_depth=3, p=1.0, dim=users)
        d = ImageDraw.Draw(img)
        text(d, (M, 284), "Users", 46, (255, 255, 255), weight="bold")
        text(d, (M, 350), "134.6GB  ·  62.9%", 44, ACCENT, weight="bold")
        a = clamp(norm(lt, 0.5, 1.2))
        if a > 0:
            text(d, (M, 1196), "一大半空间，在一个文件夹里", 40,
                 (255, 255, 255, int(255 * a)), weight="bold")
    else:
        q = norm(lt, 1.7, 3.2)
        sub = next(c for c in DRIVE["c"] if c["n"] == "Users")
        draw_map_anim(img, sub, MAP_BOX, max_depth=3, p=q, band=True)
        d = ImageDraw.Draw(img)
        text(d, (M, 284), "Users / lenovo", 46, (255, 255, 255), weight="bold")
        text(d, (M, 350), "118.0GB  ·  55.1%", 44, ACCENT, weight="bold")
        a = clamp(norm(lt, 2.4, 3.0))
        if a > 0:
            text(d, (M, 1196), "再点一层：AppData 61.2GB", 40,
                 (255, 255, 255, int(255 * a)), weight="bold")
    return img


def _punch(img, blocks, cx, cy, zoom, focus):
    """Scale the map around (cx, cy) - a camera move, not a re-layout."""
    big = Image.new("RGB", img.size, (10, 12, 17))
    draw_blocks(big, blocks, [1.0] * len(blocks), dim_others=focus)
    nw, nh = int(W * zoom), int(H * zoom)
    scaled = big.resize((nw, nh), Image.LANCZOS)
    left = int(clamp(cx * zoom - W / 2, 0, nw - W))
    top = int(clamp(cy * zoom - H / 2, 0, nh - H))
    return scaled.crop((left, top, left + W, top + H))


def scene_findings(t, lt):
    """Two numbers that make people open a terminal."""
    img = background(W, H)
    d = ImageDraw.Draw(img)
    text(d, (M, 250), "扫完之后，还有两件事", 44, DIM, weight="bold")

    rows = [
        ("重复文件", "12.8GB", "200 组", "同一个 msedge.dll 存了 5 份", PINK, 0.0),
        ("一年没动", "16.5GB", "58 个", "4GB 的模型权重，一次没用过", WARN, 1.5),
    ]
    for name, big, sub, note, col, delay in rows:
        q = norm(lt, 0.3 + delay, 1.4 + delay)
        if q <= 0:
            continue
        e = ease_out(q)
        y = 400 + (0 if delay == 0 else 430)
        d.rounded_rectangle([M, y + (1 - e) * 40, W - M, y + 340 + (1 - e) * 40],
                            radius=18, fill=(22, 26, 36, int(255 * e)),
                            outline=col + (int(90 * e),), width=2)
        text(d, (M + 40, y + 34 + (1 - e) * 40), name, 34, col,
             weight="bold") if e > 0.3 else None
        text(d, (M + 40, y + 82 + (1 - e) * 40), big, 96,
             (255, 255, 255, int(255 * e)), weight="bold")
        text(d, (M + 40, y + 210 + (1 - e) * 40), sub, 32,
             (DIM[0], DIM[1], DIM[2], int(255 * e)))
        text(d, (M + 40, y + 268 + (1 - e) * 40), note, 28,
             (FAINT[0], FAINT[1], FAINT[2], int(255 * e)))

    tail = clamp(norm(lt, 3.6, 4.4))
    if tail > 0:
        text(d, (W / 2, 1230), "一共 29GB，你根本不需要", 44,
             (255, 255, 255, int(255 * tail)), weight="bold", anchor="ma")
    return vignette(img, 0.4)


def scene_card(t, lt):
    img = background(W, H)
    d = ImageDraw.Draw(img)
    p = ease_out(norm(lt, 0, 0.7))

    glow_text(img, (W / 2 - measure("DiskMap", 108, "bold") / 2, 500 - (1 - p) * 30),
              "DiskMap", 108, (255, 255, 255), "bold")
    d = ImageDraw.Draw(img)
    text(d, (W / 2, 660), "一个 HTML 文件，离线可看", 42, ACCENT, weight="bold", anchor="ma")

    lines = [
        "扫描 214GB 全盘   ·   209 秒",
        "生成 6.7MB 报告   ·   不装任何东西",
        "面积 = 体积     颜色 = 类型",
    ]
    for i, s in enumerate(lines):
        q = ease_out(norm(lt, 0.9 + i * 0.22, 1.7 + i * 0.22))
        if q <= 0:
            continue
        text(d, (W / 2, 830 + i * 80 + (1 - q) * 24), s, 34,
             (DIM[0], DIM[1], DIM[2], int(255 * q)), anchor="ma")

    c = clamp(norm(lt, 2.2, 2.9))
    if c > 0:
        rrect(d, [W / 2 - 220, 1150, W / 2 + 220, 1246], 60,
              outline=(255, 255, 255, int(120 * c)), width=2)
        text(d, (W / 2, 1176), "python -m diskmap C:/", 33,
             (255, 255, 255, int(255 * c)), anchor="ma")
    return vignette(img, 0.45)


# ------------------------------------------------------------------ timeline
SCENES = [
    (0.0, 2.6, scene_hook),
    (2.6, 7.4, scene_bar),
    (7.4, 21.4, None),      # scene_map is special: it keeps its own clock
    (21.4, 29.4, scene_zoom),
    (29.4, 36.2, scene_findings),
    (36.2, DUR, scene_card),
]


def frame(t: float) -> Image.Image:
    for start, end, fn in SCENES:
        if start <= t < end:
            lt = t - start
            img = scene_map(t, lt) if fn is None else fn(t, lt)
            return _flash(img, t, end)
    return background(W, H)


def _flash(img, t, end):
    """A 2-frame white lift at the very end, so the loop reads as finished."""
    if DUR - t < 0.12:
        from PIL import ImageEnhance
        return ImageEnhance.Brightness(img).enhance(1.25)
    return img


def main(argv):
    if len(argv) > 1 and argv[1] == "stills":
        times = [float(x) for x in argv[2:]] or [0.5, 3.5, 5.5, 9, 12, 16, 20, 23, 26, 30, 33, 38]
        run(frame, Path("out/v1"), DUR, stills=times)
        print("stills in out/v1")
        return 0
    run(frame, Path("out/v1-cdrive.mp4"), DUR, fps=FPS, size=(W, H))
    print("wrote out/v1-cdrive.mp4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
