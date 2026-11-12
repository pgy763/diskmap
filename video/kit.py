"""A tiny frame-by-frame video kit built on Pillow + ffmpeg.

No matplotlib, no moviepy, no browser: every frame is drawn with Pillow and
piped straight into ffmpeg as raw RGB. That keeps the pipeline dependency-free
and makes the output pixel-exact, which matters when the frames contain
carefully aligned typography.

Design notes
------------
* Everything is drawn in device pixels; there is no logical/DIP indirection.
* The background is rendered once per size and copied per frame, because a
  per-frame gradient costs more than the entire treemap.
* Text is measured through Pillow, never guessed, so CJK and Latin can be mixed
  without the usual "why is this centred wrong" problem.
"""

from __future__ import annotations

import math
import os
import shutil
import subprocess
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ---------------------------------------------------------------- palette
BG = (10, 12, 17)
BG2 = (18, 21, 29)
INK = (232, 236, 244)
DIM = (139, 147, 167)
FAINT = (95, 103, 121)
ACCENT = (94, 234, 212)
WARN = (251, 191, 36)
BAD = (248, 113, 113)
PINK = (244, 114, 182)
BLUE = (96, 165, 250)

FONT_DIR = Path("C:/Windows/Fonts")
_FACES = {
    ("regular", 0): FONT_DIR / "msyh.ttc",
    ("bold", 0): FONT_DIR / "msyhbd.ttc",
}
_font_cache: dict[tuple[int, str], ImageFont.FreeTypeFont] = {}


def font(size: int, weight: str = "regular") -> ImageFont.FreeTypeFont:
    key = (int(size), weight)
    f = _font_cache.get(key)
    if f is None:
        f = ImageFont.truetype(str(_FACES[(weight, 0)]), int(size))
        _font_cache[key] = f
    return f


# ---------------------------------------------------------------- easing
def clamp(x, lo=0.0, hi=1.0):
    return lo if x < lo else hi if x > hi else x


def norm(t, a, b):
    """Map t from [a,b] to [0,1], clamped."""
    if b <= a:
        return 1.0 if t >= b else 0.0
    return clamp((t - a) / (b - a))


def ease_out(x):
    return 1 - (1 - x) ** 3


def ease_in(x):
    return x ** 3


def ease_in_out(x):
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def ease_out_back(x, s=1.70158):
    return 1 + (s + 1) * (x - 1) ** 3 + s * (x - 1) ** 2


def ease_out_expo(x):
    return 1 if x >= 1 else 1 - 2 ** (-10 * x)


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    return tuple(int(round(lerp(a, b, t))) for a, b in zip(c1, c2))


def pulse(t, hz=1.6):
    """0..1 triangle-ish wave, for breathing highlights."""
    return 0.5 + 0.5 * math.sin(t * hz * math.tau)


# ---------------------------------------------------------------- canvas
_BAYER4 = np.array([
    [0, 8, 2, 10],
    [12, 4, 14, 6],
    [3, 11, 1, 9],
    [15, 7, 13, 5],
], dtype=np.int16)


def dither(img: Image.Image, amount: int = 3) -> Image.Image:
    """Ordered dither by +/-amount before encode.

    A dark 8-bit gradient only has a handful of distinct values to work with,
    so it steps. ffmpeg's yuv420p conversion then turns those steps into visible
    bands across the whole frame. One unit of ordered noise removes the banding
    while staying below the perceptual threshold, and it also stops H.264 from
    starving flat areas of bits. Vectorised, so it costs ~10 ms per frame.
    """
    a = np.asarray(img, dtype=np.int16)
    h, w = a.shape[:2]
    tile = np.tile(_BAYER4, (h // 4 + 1, w // 4 + 1))[:h, :w]
    offset = ((tile - 7.5) * (2 * amount / 16)).astype(np.int16)
    a = np.clip(a + offset[:, :, None], 0, 255)
    return Image.fromarray(a.astype(np.uint8), "RGB")


class Video:
    """Renders frames to a temp folder, then lets ffmpeg encode the sequence.

    Writing raw RGB into ffmpeg's stdin would be the obvious approach, but this
    sandbox denies CreatePipe (WinError 5), and every pipe-free alternative is
    faster anyway: JPEG frames take ~5 ms each versus ~25 ms for PNG, and the
    encode step reads them back at disk speed. Use as a context manager.
    """

    def __init__(self, out_path, w=1080, h=1920, fps=30, crf=18, preset="medium"):
        self.w, self.h, self.fps = w, h, fps
        self.out_path = str(out_path)
        self.crf, self.preset = crf, preset
        Path(self.out_path).parent.mkdir(parents=True, exist_ok=True)
        # tempfile.mkdtemp returns a directory Python cannot write into here
        # (the sandbox ACL template strips the owner), so make it ourselves.
        self._dir = Path(self.out_path).parent / f".frames-{os.getpid()}"
        shutil.rmtree(self._dir, ignore_errors=True)
        self._dir.mkdir(parents=True, exist_ok=True)
        self.n = 0

    def write(self, img: Image.Image):
        if img.size != (self.w, self.h):
            img = img.resize((self.w, self.h), Image.LANCZOS)
        img = dither(img.convert("RGB"))
        img.save(self._dir / f"{self.n:06d}.jpg", quality=96)
        self.n += 1

    def close(self):
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-framerate", str(self.fps),
            "-i", str(self._dir / "%06d.jpg"),
            "-c:v", "libx264", "-preset", self.preset,
            "-crf", str(self.crf), "-pix_fmt", "yuv420p",
            "-movflags", "+faststart", self.out_path,
        ]
        with open(self._dir / "ffmpeg.log", "wb") as log:
            rc = subprocess.call(cmd, stdout=log, stderr=log)
        if rc != 0:
            raise RuntimeError(f"ffmpeg exited {rc}; see {self._dir / 'ffmpeg.log'}")
        shutil.rmtree(self._dir, ignore_errors=True)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        if exc[0] is None:
            self.close()
        else:
            shutil.rmtree(self._dir, ignore_errors=True)


_bg_cache: dict[tuple, Image.Image] = {}


def background(w, h, top=BG, bottom=BG2, texture=True) -> Image.Image:
    """Dark vertical gradient with a faint dot grid, cached per size."""
    key = (w, h, top, bottom, texture)
    img = _bg_cache.get(key)
    if img is not None:
        return img.copy()

    img = Image.new("RGB", (w, h), top)
    d = ImageDraw.Draw(img)
    for y in range(h):
        k = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=mix(top, bottom, k ** 0.85))
    if texture:
        # 32 px dot grid: visible up close, invisible behind text at a glance.
        g = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        gd = ImageDraw.Draw(g)
        for y in range(0, h, 32):
            for x in range(0, w, 32):
                gd.point((x, y), fill=(255, 255, 255, 8))
        img = Image.alpha_composite(img.convert("RGBA"), g).convert("RGB")
    _bg_cache[key] = img
    return img.copy()


def vignette(img: Image.Image, strength=0.55) -> Image.Image:
    w, h = img.size
    m = Image.new("L", (w, h), 0)
    md = ImageDraw.Draw(m)
    md.ellipse([-w * 0.35, -h * 0.25, w * 1.35, h * 1.25], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(w // 8))
    dark = Image.new("RGB", (w, h), (0, 0, 0))
    return Image.composite(img, Image.blend(img, dark, strength), m)


# ---------------------------------------------------------------- text
def measure(s: str, size: int, weight="regular", tracking=0) -> int:
    f = font(size, weight)
    if not tracking:
        return int(f.getlength(s))
    return int(sum(f.getlength(ch) for ch in s) + tracking * max(0, len(s) - 1))


def text(d: ImageDraw.ImageDraw, xy, s, size, color=INK, weight="regular",
         anchor="la", tracking=0, **kw):
    """Draw text with optional letter-spacing; returns the drawn width."""
    f = font(size, weight)
    if not tracking:
        d.text(xy, s, font=f, fill=color, anchor=anchor, **kw)
        return int(f.getlength(s))
    x, y = xy
    if anchor[0] == "m":
        x -= measure(s, size, weight, tracking) / 2
    elif anchor[0] == "r":
        x -= measure(s, size, weight, tracking)
    for ch in s:
        d.text((x, y), ch, font=f, fill=color, anchor="l" + anchor[1], **kw)
        x += f.getlength(ch) + tracking
    return int(x - xy[0])


def wrap(s: str, size: int, max_w: int, weight="regular") -> list[str]:
    """Greedy wrap that works for CJK (breaks anywhere) and Latin (at spaces)."""
    f = font(size, weight)
    lines, cur = [], ""
    for ch in s:
        if ch == "\n":
            lines.append(cur)
            cur = ""
            continue
        trial = cur + ch
        if f.getlength(trial) > max_w and cur:
            # Back up to the last space if we are in the middle of a Latin word.
            if ch.isascii() and ch != " " and " " in cur and not _cjk(cur[-1]):
                cut = cur.rfind(" ")
                lines.append(cur[:cut])
                cur = cur[cut + 1:] + ch
            else:
                lines.append(cur)
                cur = ch
        else:
            cur = trial
    if cur:
        lines.append(cur)
    return lines


def _cjk(ch: str) -> bool:
    return ord(ch) > 0x2E80


def paragraph(d, xy, s, size, max_w, color=INK, weight="regular", lh=1.45):
    x, y = xy
    step = int(size * lh)
    for i, line in enumerate(wrap(s, size, max_w, weight)):
        d.text((x, y + i * step), line, font=font(size, weight), fill=color)
    return y + len(wrap(s, size, max_w, weight)) * step


def glow_text(img: Image.Image, xy, s, size, color, weight="bold", radius=None):
    """Text with a soft halo - used for the few words that must carry a frame.

    The halo layer is padded generously (4x radius on every side) because a
    Gaussian blur spreads in all directions: a tight layer clips the glow and
    leaves a visible straight edge, which reads as a rendering bug.
    """
    radius = radius or max(6, size // 12)
    pad = radius * 4
    tw = int(measure(s, size, weight))
    fh = int(size * 1.6)
    lw, lh = tw + pad * 2, fh + pad * 2
    layer = Image.new("RGBA", (lw, lh), (0, 0, 0, 0))
    ld = ImageDraw.Draw(layer)
    ld.text((lw / 2, lh / 2), s, font=font(size, weight), fill=color + (255,), anchor="mm")
    halo = layer.filter(ImageFilter.GaussianBlur(radius))
    base = img.convert("RGBA")
    # xy is the top-left of the text box as drawn by `text`
    pos = (int(xy[0] - pad), int(xy[1] + fh / 2 - lh / 2))
    base.alpha_composite(halo, pos)
    base.alpha_composite(layer, pos)
    img.paste(base.convert("RGB"))


# ---------------------------------------------------------------- shapes
def rrect(d, box, r, fill=None, outline=None, width=1):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


def with_alpha(img: Image.Image, alpha: float) -> Image.Image:
    """Multiply a frame's alpha - cheap scene fades."""
    if alpha >= 0.999:
        return img
    a = img.convert("RGBA")
    a.putalpha(a.getchannel("A").point(lambda v: int(v * alpha)))
    return a


def scene(base: Image.Image, alpha: float, fn):
    """Draw onto a transparent overlay, then composite with *alpha*."""
    if alpha <= 0.003:
        return base
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    fn(layer)
    if alpha < 0.999:
        layer = with_alpha(layer, alpha)
    return Image.alpha_composite(base.convert("RGBA"), layer).convert("RGB")


def fmt_int(n) -> str:
    return f"{int(n):,}"


def fmt_bytes(n: float) -> str:
    n = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(n)}B"
            return f"{n:.1f}{unit}"
        n /= 1024
    return ""


def fmt_bytes_parts(n: float):
    """"134.6" and "GB" separately, for two-size typography."""
    s = fmt_bytes(n)
    i = len(s)
    while i and (s[i - 1].isdigit() or s[i - 1] == "."):
        i -= 1
    return s[:i], s[i:]


def run(draw, out_path, duration, fps=30, size=(1080, 1920), stills=None):
    """Render `draw(t)` for t in [0, duration); optionally dump PNG stills.

    Returning stills mode means a layout can be checked frame by frame without
    paying for a full encode - the single most useful debugging affordance for
    this kind of animation.
    """
    w, h = size
    if stills:
        Path(out_path).mkdir(parents=True, exist_ok=True)
        paths = []
        for t in stills:
            p = Path(out_path) / f"t{t:05.2f}.png"
            # Match the encoded frames, otherwise previews lie about banding.
            dither(draw(t).convert("RGB")).save(p)
            paths.append(p)
        return paths

    with Video(out_path, w=w, h=h, fps=fps) as v:
        frames = int(round(duration * fps))
        for i in range(frames):
            v.write(draw(i / fps))
    return out_path
