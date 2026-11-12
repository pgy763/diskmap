"""Video 2 - "两把尺子": the same folder, measured by bytes and by file count.

The whole short rests on one observation that a size-only disk tool hides: the
folders that eat the most space and the folders that hold the most files are
almost disjoint sets. .tmp-video is 11% of the bytes but 0.4% of the files;
hello-ai-backend is 12% of the bytes and 26% of the files.

So instead of cutting to a second screenshot, the map *re-sorts itself* on
screen: every frame re-runs squarify on a weight that blends byte share into
file-count share. Blocks slide, others grow, and the ranking underneath the map
flips in front of the viewer.

Structure:
  0.0 - 3.2   hook     one folder, two rulers
  3.2 - 13.4  morph    bytes -> file count, live, with a live top-3 list
 13.4 - 20.6  contrast .tmp-video vs hello-ai-backend: same size, 74x the files
 20.6 - 30.0  junk     half of all files are node_modules and target
 30.0 - 37.0  card     two views, one command
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PIL import Image, ImageDraw  # noqa: E402

from diskmap.render import human, squarify  # noqa: E402
from video.kit import (  # noqa: E402
    ACCENT, BLUE, DIM, FAINT, INK, PINK, WARN,
    background, clamp, ease_in_out, ease_out, font, fmt_int,
    glow_text, measure, norm, rrect, run, text, vignette,
)
from video.v1 import _fit_name, _hatch  # noqa: E402
from video.ws_data import JUNK, TREE  # noqa: E402

W, H = 1080, 1920
FPS = 30
DUR = 37.0

M = 72
MAP_BOX = (M, 440, W - 2 * M, 520)
MAP_AREA = MAP_BOX[2] * MAP_BOX[3]

KIND_COLOR = {"deps": ACCENT, "build": WARN, "cache": BLUE, "venv": PINK}
KIND_NAME = {"deps": "依赖", "build": "构建产物", "cache": "缓存", "venv": "虚拟环境"}

# Colour by *what kind of folder it is*, not by file extension: on a source
# tree every leaf is code, so extension colouring paints the whole map one
# grey. Regenerable folders in accent colours and everything else in slate
# makes the count view self-explanatory - the map turns teal where the mess is.
KIND_OF = {"node_modules": "deps", "target": "build", "build": "build",
           "dist": "build", ".gradle": "cache", "__pycache__": "cache",
           ".venv": "venv", "venv": "venv", ".next": "build",
           ".pytest_cache": "cache", ".mypy_cache": "cache", ".ruff_cache": "cache"}
FILL = {"deps": ACCENT, "build": WARN, "cache": PINK, "venv": PINK,
        "git": (71, 85, 105), "other": (58, 70, 92)}


def _kind(n):
    return KIND_OF.get(n["n"].lower(), "git" if n["n"].lower() == ".git" else "other")


def _fill(node, depth):
    k = [1.0, 0.92, 0.84][min(depth - 1, 2)]
    return tuple(int(v * k) for v in FILL[_kind(node)])

TOTAL_S = TREE["s"]
TOTAL_K = TREE["k"]
JUNK_S = sum(j["size"] for j in JUNK)
JUNK_K = sum(j["count"] for j in JUNK)


# ------------------------------------------------------------------ map
def morph_map(img, node, box, t, *, depth=1, max_depth=3, band=True):
    """Squarified map whose weights blend from byte share to file-count share.

    Re-running the layout every frame (instead of cross-fading two pictures) is
    what makes the change legible: a block that grows is a block that got
    heavier under the new ruler, and the eye can follow it.
    """
    d = ImageDraw.Draw(img, "RGBA")
    x, y, w, h = box
    kids = [c for c in node.get("c", []) if c["s"] > 0]
    if not kids:
        return

    body = (x, y, w, h)
    if band and depth <= 2:
        bh = 44 if depth == 1 else 34
        if h > bh * 2.2 and w > bh * 3.4:
            d.rectangle([x, y, x + w, y + bh], fill=(17, 20, 28, 255))
            fs = 25 if depth == 1 else 19
            d.text((x + 12, y + bh / 2 - fs * 0.75),
                   _fit_name(d, node["n"], fs, w - 24), font=font(fs, "bold"),
                   fill=(232, 236, 244))
            body = (x, y + bh, w, h - bh)

    ts = sum(c["s"] for c in kids) or 1
    tk = sum(c["k"] for c in kids) or 1
    items = [((1 - t) * (c["s"] / ts) + t * (c["k"] / tk), c) for c in kids]

    for rx, ry, rw, rh, child in squarify(items, *body):
        if rw < 1 or rh < 1:
            continue
        box2 = (rx, ry, rw, rh)
        col = _fill(child, depth)
        d.rectangle([rx, ry, rx + rw, ry + rh], fill=col + (255,),
                    outline=(255, 255, 255, 22))
        if not child.get("c") and rw * rh > 0.04 * MAP_AREA:
            _hatch(d, box2, 40)
        if child.get("c") and depth < max_depth and rw > 74 and rh > 62:
            morph_map(img, child, box2, t, depth=depth + 1,
                      max_depth=max_depth, band=band)
        elif rw > 100 and rh > 60:
            fs = 23 if depth == 1 else 20
            d.text((rx + 10, ry + 7), _fit_name(d, child["n"], fs, rw - 20),
                   font=font(fs, "bold"), fill=(255, 255, 255, 240))
            if rh > 92:
                # Both rulers are on screen at once while morphing, so show the
                # measurement that currently dominates and fade the other out.
                a_s = clamp(1 - (t - 0.30) / 0.18)
                a_k = clamp((t - 0.48) / 0.18)
                if a_s > 0:
                    d.text((rx + 10, ry + 12 + fs), human(child["s"]),
                           font=font(fs - 5), fill=(255, 255, 255, int(150 * a_s)))
                if a_k > 0:
                    d.text((rx + 10, ry + 12 + fs), fmt_int(child["k"]) + " 个",
                           font=font(fs - 5), fill=(255, 255, 255, int(200 * a_k)))


def _weight(node, t):
    return (1 - t) * node["s"] / TOTAL_S + t * node["k"] / TOTAL_K


# ------------------------------------------------------------------ scenes
def scene_hook(t, lt):
    img = background(W, H)
    d = ImageDraw.Draw(img)

    # Frame 0 must already carry the hook. On a vertical feed the first frame is
    # the thumbnail and the only thing a fast scroller sees. Measured: fading
    # from nothing gave a literally black first frame (max channel 28), and
    # showing only line 1 read as an unfinished sentence. Both lines are up at
    # frame 0 so the thumbnail says "same folder, two rulers" on its own.
    q1 = 0.82 + 0.18 * ease_out(norm(lt, 0.0, 0.8))
    text(d, (W / 2, 560 + (1 - q1) * 26), "同一个文件夹", 76,
         (255, 255, 255, int(255 * q1)), weight="bold", anchor="ma")
    q2 = 0.66 + 0.34 * ease_out(norm(lt, 0.0, 0.9))
    text(d, (W / 2, 680 + (1 - q2) * 26), "换一把尺子量", 76,
         (255, 255, 255, int(255 * q2)), weight="bold", anchor="ma")

    q3 = ease_out(norm(lt, 1.3, 2.0))
    if q3 > 0:
        text(d, (W / 2, 1030 + (1 - q3) * 24),
             "完全是另一个世界", 60, ACCENT + (int(255 * q3),),
             weight="bold", anchor="ma")
    return vignette(img, 0.5)


def _top_list(img, t, y0=986):
    """Top 3 by the current weight, re-sorted live under the map."""
    d = ImageDraw.Draw(img, "RGBA")
    rows = sorted(TREE["c"], key=lambda c: -_weight(c, t))[:3]
    for i, c in enumerate(rows):
        y = y0 + i * 86
        col = FILL[_kind(c)]
        a = clamp(norm(t, 0.0, 0.22) if i == 0 else 1.0)
        d.rounded_rectangle([M, y + 12, M + 7, y + 62], radius=3, fill=col)
        text(d, (M + 26, y + 8), c["n"], 36, (255, 255, 255, int(240 * a)),
             weight="bold")
        share = (1 - t) * c["s"] / TOTAL_S + t * c["k"] / TOTAL_K
        text(d, (W - M, y + 8), f"{share * 100:.1f}%", 36,
             (255, 255, 255, int(200 * a)), weight="bold", anchor="ra")
        sub = human(c["s"]) if t < 0.5 else fmt_int(c["k"]) + " 个文件"
        text(d, (W - M, y + 48), sub, 24, DIM + (int(210 * a),), anchor="ra")


def scene_morph(t, lt):
    img = background(W, H)
    tt = ease_in_out(norm(lt, 1.1, 6.4))

    head = ease_out(norm(lt, 0, 0.5))
    text(d0 := ImageDraw.Draw(img), (M, 210 - (1 - head) * 16),
         "D:\\Github-code  ·  2.95GB  ·  21,256 个文件", 30, DIM, weight="bold")

    # Ruler label: the words change at the exact moment the layout does.
    lab_y = 272
    a1 = clamp(1 - norm(tt, 0.42, 0.58))
    a2 = clamp(norm(tt, 0.42, 0.58))
    if a1 > 0:
        text(d0, (M, lab_y), "面积 = 体积", 52, (255, 255, 255, int(255 * a1)),
             weight="bold")
    if a2 > 0:
        text(d0, (M, lab_y), "面积 = 文件数量", 52, ACCENT + (int(255 * a2),),
             weight="bold")

    d0.rounded_rectangle([MAP_BOX[0] - 4, MAP_BOX[1] - 4, MAP_BOX[0] + MAP_BOX[2] + 4,
                          MAP_BOX[1] + MAP_BOX[3] + 4], radius=10,
                         outline=(255, 255, 255, 26), width=2)
    morph_map(img, TREE, MAP_BOX, tt)

    _top_list(img, tt, y0=986)

    cap = clamp(norm(lt, 6.6, 7.4))
    if cap > 0:
        text(ImageDraw.Draw(img), (M, 1228),
             "体积最大的，往往不是文件最多的", 34,
             (255, 255, 255, int(255 * cap)), weight="bold")
    return img


def scene_contrast(t, lt):
    """Same size, 74x the file count. The clearest possible proof."""
    img = background(W, H)
    # RGBA: the two cards rise in with 4-tuple fills; plain RGB mode drops the
    # alpha byte and makes them appear fully formed on the first frame.
    d = ImageDraw.Draw(img, "RGBA")
    text(d, (M, 220), "两个文件夹，一样大", 38, DIM, weight="bold")

    cards = [
        (".tmp-video", "334.6MB", 76, "一个文件平均 4.4MB", WARN, 0.0),
        ("hello-ai-backend", "355.6MB", 5613, "一个文件平均 63KB", BLUE, 0.55),
    ]
    y = 340
    for name, sz, k, note, col, delay in cards:
        q = norm(lt, 0.2 + delay, 1.1 + delay)
        if q <= 0:
            continue
        e = ease_out(q)
        d.rounded_rectangle([M, y + (1 - e) * 34, W - M, y + 300 + (1 - e) * 34],
                            radius=18, fill=(22, 26, 36, int(255 * e)),
                            outline=col + (int(80 * e),), width=2)
        text(d, (M + 34, y + 24 + (1 - e) * 34), name, 36,
             (255, 255, 255, int(255 * e)), weight="bold")
        text(d, (M + 34, y + 76 + (1 - e) * 34), sz, 66, col + (int(255 * e),),
             weight="bold")
        text(d, (M + 34, y + 164 + (1 - e) * 34), fmt_int(k) + " 个文件", 44,
             (255, 255, 255, int(230 * e)), weight="bold")
        text(d, (M + 34, y + 232 + (1 - e) * 34), note, 27,
             (FAINT[0], FAINT[1], FAINT[2], int(255 * e)))
        y += 336

    q = ease_out(norm(lt, 2.6, 3.4))
    if q > 0:
        text(d, (W / 2, 1036 + (1 - q) * 20), "74 倍", 108,
             ACCENT + (int(255 * q),), weight="bold", anchor="ma")
        text(d, (W / 2, 1168), "文件数量差 74 倍，体积差 6%", 32,
             (DIM[0], DIM[1], DIM[2], int(255 * q)), anchor="ma")
    return vignette(img, 0.45)


def scene_junk(t, lt):
    """Half of every file on disk is something a build can regenerate."""
    img = background(W, H)
    # RGBA draw context is required here: every row fades in with a 4-tuple
    # fill. In plain "RGB" mode PIL silently drops the alpha byte, so the bars
    # rendered fully opaque and the 6/255 track below came out solid white --
    # all six rows looked equally full.
    d = ImageDraw.Draw(img, "RGBA")
    text(d, (M, 216), "还有一件事：文件数的一半是垃圾", 36, DIM, weight="bold")

    q = ease_out(norm(lt, 0.1, 0.9))
    if q > 0:
        text(d, (M, 268), "10,625", 96, (255, 255, 255, int(255 * q)),
             weight="bold")
        text(d, (M + measure("10,625 ", 96, "bold"), 300), "个文件", 42,
             (DIM[0], DIM[1], DIM[2], int(255 * q)))
        text(d, (W - M, 300), "49.9% 的文件", 36, ACCENT + (int(255 * q),),
             weight="bold", anchor="ra")
        text(d, (W - M, 350), "965.1MB  ·  32.6% 的体积", 32,
             (DIM[0], DIM[1], DIM[2], int(255 * q)), anchor="ra")

    rows = JUNK[:6]
    top = max(r["count"] for r in rows) or 1
    base_y = 396
    for i, r in enumerate(rows):
        q = norm(lt, 0.9 + i * 0.16, 1.6 + i * 0.16)
        if q <= 0:
            break
        e = ease_out(q)
        y = base_y + i * 124
        col = KIND_COLOR.get(r["kind"], DIM)
        d.rectangle([M, y + (1 - e) * 18, M + 6, y + 82 + (1 - e) * 18],
                    fill=col + (int(255 * e),))
        name = r["path"].replace("\\", " / ")
        if len(name) > 40:
            name = "…" + name[-39:]
        text(d, (M + 24, y + (1 - e) * 18), name, 28,
             (255, 255, 255, int(240 * e)), weight="bold")
        text(d, (W - M, y + 2 + (1 - e) * 18), KIND_NAME.get(r["kind"], r["kind"]),
             22, col + (int(255 * e),), weight="bold", anchor="ra")
        text(d, (M + 24, y + 38 + (1 - e) * 18),
             f"{human(r['size'])}  ·  {fmt_int(r['count'])} 个文件", 25,
             (DIM[0], DIM[1], DIM[2], int(220 * e)))
        # The bar is scaled by file count on purpose: 4,461 node_modules files
        # must visibly outrank a 108MB jar folder that holds 27 files.
        # A faint track behind it is what makes that readable: without the
        # track a 27-file row is a 6px stub that looks like a rendering bug
        # rather than "0.6% of the biggest one". Keep the track barely above
        # the background -- at 14/255 it read as a nearly full white bar and
        # the rows all looked identical again.
        track_w = W - 2 * M - 48
        bw = track_w * (r["count"] / top)
        d.rounded_rectangle([M + 24, y + 74 + (1 - e) * 18,
                             M + 24 + track_w, y + 84 + (1 - e) * 18],
                            radius=5, fill=(255, 255, 255, int(6 * e)))
        d.rounded_rectangle([M + 24, y + 74 + (1 - e) * 18,
                             M + 24 + max(6, bw), y + 84 + (1 - e) * 18],
                            radius=5, fill=col + (int(150 * e),))

    q = ease_out(norm(lt, 3.0, 3.9))
    if q > 0:
        text(d, (M, 1146 + (1 - q) * 20), "删掉，重新构建就回来了", 42,
             (255, 255, 255, int(255 * q)), weight="bold")
        text(d, (M, 1206), "但 DiskMap 得先告诉你它在哪", 30,
             (DIM[0], DIM[1], DIM[2], int(255 * q)))
    return vignette(img, 0.45)


def scene_card(t, lt):
    img = background(W, H)
    # RGBA for the same reason as the other scenes: the command capsule's
    # outline and the three feature lines carry an alpha ramp.
    p = ease_out(norm(lt, 0, 0.7))
    glow_text(img, (W / 2 - measure("DiskMap", 104, "bold") / 2, 480 - (1 - p) * 28),
              "DiskMap", 104, (255, 255, 255), "bold")
    d = ImageDraw.Draw(img, "RGBA")
    text(d, (W / 2, 650), "一把尺子不够，那就两把", 42, ACCENT, weight="bold",
         anchor="ma")

    lines = [
        "按体积  ×  按文件数，一键切换",
        "自动认出 node_modules / target / .venv",
        "输出一个 HTML，离线打开，不用装",
    ]
    for i, s in enumerate(lines):
        q = ease_out(norm(lt, 0.85 + i * 0.2, 1.6 + i * 0.2))
        if q <= 0:
            continue
        text(d, (W / 2, 796 + i * 80 + (1 - q) * 22), s, 32,
             (DIM[0], DIM[1], DIM[2], int(255 * q)), anchor="ma")

    c = clamp(norm(lt, 2.0, 2.7))
    if c > 0:
        rrect(d, [W / 2 - 250, 1104, W / 2 + 250, 1204], 62,
              outline=(255, 255, 255, int(120 * c)), width=2)
        text(d, (W / 2, 1130), "python -m diskmap . --all", 32,
             (255, 255, 255, int(255 * c)), anchor="ma")
        text(d, (W / 2, 1248), "扫完直接翻到「依赖缓存」那一页", 28,
             (FAINT[0], FAINT[1], FAINT[2], int(255 * c)), anchor="ma")
    return vignette(img, 0.45)


# ------------------------------------------------------------------ timeline
SCENES = [
    (0.0, 3.2, scene_hook),
    (3.2, 13.4, scene_morph),
    (13.4, 20.6, scene_contrast),
    (20.6, 30.0, scene_junk),
    (30.0, DUR, scene_card),
]


def frame(t: float) -> Image.Image:
    for start, end, fn in SCENES:
        if start <= t < end:
            return fn(t, t - start)
    return background(W, H)


def main(argv):
    if len(argv) > 1 and argv[1] == "stills":
        times = [float(x) for x in argv[2:]] or [
            1.0, 2.6, 4.0, 5.4, 6.6, 8.0, 9.6, 11.0, 12.9,
            14.5, 16.5, 18.5, 22.0, 24.0, 26.0, 28.5, 32.0, 35.5]
        run(frame, Path("out/v2"), DUR, stills=times)
        print("stills in out/v2")
        return 0
    run(frame, Path("out/v2-two-rulers.mp4"), DUR, fps=FPS, size=(W, H))
    print("wrote out/v2-two-rulers.mp4")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
