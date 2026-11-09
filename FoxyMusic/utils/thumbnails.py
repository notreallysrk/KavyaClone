# ===========================================================
# 🖼 NOW PLAYING THUMBNAIL — blurred song-image background
#
# Design: jo song play ho raha hai uski image poore background
# me BLUR hoke lagti hai, beech me white player card, album art
# (square, card se bahar nikli hui), artist + title, progress bar
# aur controls.
#
# Use (purane get_thumb / gen_thumb ki jagah):
#   from ShiviMusic.utils.thumbnails import get_thumb
#   thumb = await get_thumb(videoid)
# ===========================================================

import asyncio
import io
import os
import re

import aiohttp
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1280, 720
BLUR_RADIUS = 38  # zyada = aur blur

_ASSETS = os.path.join(os.path.dirname(__file__), "..", "assets")
_FONT_CANDIDATES = [
    os.path.join(_ASSETS, "font.ttf"),
    os.path.join(_ASSETS, "font2.ttf"),
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
]


def _font(size: int, bold: bool = False):
    cands = list(_FONT_CANDIDATES)
    if bold:
        cands.insert(0, "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
    for p in cands:
        try:
            return ImageFont.truetype(p, size)
        except Exception:
            continue
    return ImageFont.load_default()


def _cover_crop(img: Image.Image, w: int, h: int) -> Image.Image:
    iw, ih = img.size
    sc = max(w / iw, h / ih)
    img = img.resize((int(iw * sc) + 1, int(ih * sc) + 1), Image.LANCZOS)
    l, t = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((l, t, l + w, t + h))


def _blurred_background(cover: Image.Image) -> Image.Image:
    bg = _cover_crop(cover, W, H).filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
    # halka sa dark overlay taaki card/text clear dikhe
    dark = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.blend(bg, dark, 0.28)


def _rounded(img: Image.Image, radius: int) -> Image.Image:
    img = img.convert("RGBA")
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, *img.size), radius, fill=255)
    img.putalpha(mask)
    return img


def _shadow(canvas: Image.Image, box, radius: int, blur: int = 28, alpha: int = 110, dy: int = 14):
    layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    x0, y0, x1, y1 = box
    ImageDraw.Draw(layer).rounded_rectangle(
        (x0, y0 + dy, x1, y1 + dy), radius, fill=(0, 0, 0, alpha)
    )
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(layer)


def _fit_text(draw, text: str, font, max_w: int) -> str:
    if draw.textlength(text, font=font) <= max_w:
        return text
    while text and draw.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


def _spaced(draw, xy, text: str, font, fill, spacing: int):
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + spacing


def _clean_title(t) -> str:
    t = str(t or "")
    t = re.sub(r"\((.*?)\)|\[(.*?)\]", "", t or "")
    t = re.sub(r"\b(official|video|audio|lyrical|lyrics|full song|hd|4k)\b", "", t, flags=re.I)
    return re.sub(r"\s+", " ", t).strip(" -|") or (t or "Unknown")


def compose_thumb(cover: Image.Image, title: str, artist: str, duration: str, path: str):
    cover = cover.convert("RGB")
    canvas = _blurred_background(cover).convert("RGBA")
    d = ImageDraw.Draw(canvas)

    # ---- white card ----
    cx0, cy0, cx1, cy1 = 190, 215, 1090, 505
    _shadow(canvas, (cx0, cy0, cx1, cy1), 26, blur=30, alpha=90)
    card = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    ImageDraw.Draw(card).rounded_rectangle(
        (cx0, cy0, cx1, cy1), 26, fill=(255, 255, 255, 245)
    )
    canvas.alpha_composite(card)
    d = ImageDraw.Draw(canvas)

    # ---- album art (card se bahar nikla hua) ----
    S = 390
    ax, ay = 300, (cy0 + cy1) // 2 - S // 2
    _shadow(canvas, (ax, ay, ax + S, ay + S), 14, blur=26, alpha=140, dy=16)
    art = _rounded(_cover_crop(cover, S, S), 14)
    canvas.alpha_composite(art, (ax, ay))
    d = ImageDraw.Draw(canvas)

    ink = (22, 22, 22, 255)
    mid = (110, 110, 110, 255)

    # ---- left icons: heart, plus, share ----
    ix, cy = 245, (cy0 + cy1) // 2
    # heart
    hy = cy - 70
    d.ellipse((ix - 15, hy - 13, ix, hy + 2), outline=ink, width=3)
    d.ellipse((ix, hy - 13, ix + 15, hy + 2), outline=ink, width=3)
    d.polygon([(ix - 14, hy - 1), (ix + 14, hy - 1), (ix, hy + 15)], fill=(255, 255, 255, 255))
    d.line([(ix - 14, hy + 1), (ix, hy + 16), (ix + 14, hy + 1)], fill=ink, width=3)
    # plus
    d.line([(ix - 14, cy), (ix + 14, cy)], fill=ink, width=3)
    d.line([(ix, cy - 14), (ix, cy + 14)], fill=ink, width=3)
    # share
    sy = cy + 70
    d.line([(ix - 14, sy - 2), (ix - 14, sy + 14), (ix + 14, sy + 14), (ix + 14, sy - 2)], fill=ink, width=3)
    d.line([(ix, sy + 6), (ix, sy - 16)], fill=ink, width=3)
    d.polygon([(ix, sy - 20), (ix - 8, sy - 10), (ix + 8, sy - 10)], fill=ink)

    # ---- text ----
    tx0, tx1 = 725, 1045
    max_w = tx1 - tx0
    f_artist, f_title, f_small = _font(28, True), _font(30), _font(17)
    artist_txt = (artist or "Unknown").upper()
    while d.textlength(artist_txt, font=f_artist) + 5 * len(artist_txt) > max_w and len(artist_txt) > 3:
        artist_txt = artist_txt[:-2] + "…" if not artist_txt.endswith("…") else artist_txt[:-2] + "…"
    _spaced(d, (tx0, 262), artist_txt, f_artist, ink, 5)
    d.text((tx0, 312), _fit_text(d, _clean_title(title), f_title, max_w), font=f_title, fill=ink)

    # ---- progress bar ----
    by = 388
    d.rounded_rectangle((tx0, by, tx1, by + 4), 2, fill=(222, 226, 232, 255))
    fill_x = tx0 + int(max_w * 0.07)
    d.rounded_rectangle((tx0, by, fill_x, by + 4), 2, fill=ink)
    d.text((tx0, by + 14), "0:00", font=f_small, fill=ink)
    d.text((tx1, by + 14), duration or "0:00", font=f_small, fill=ink, anchor="ra")

    # ---- controls ----
    mx, my = (tx0 + tx1) // 2, 460
    d.ellipse((mx - 28, my - 28, mx + 28, my + 28), fill=ink)
    d.rectangle((mx - 9, my - 11, mx - 3, my + 11), fill=(255, 255, 255, 255))
    d.rectangle((mx + 3, my - 11, mx + 9, my + 11), fill=(255, 255, 255, 255))
    for off, sign in ((-95, -1), (95, 1)):  # prev / next
        x = mx + off
        for k in (0, 14):
            if sign < 0:
                d.polygon([(x - k + 8, my - 9), (x - k + 8, my + 9), (x - k - 6, my)], fill=ink)
            else:
                d.polygon([(x + k - 8, my - 9), (x + k - 8, my + 9), (x + k + 6, my)], fill=ink)

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    canvas.convert("RGB").save(path, "JPEG", quality=92)
    return path


async def _download(session, vidid: str):
    for q in ("maxresdefault", "sddefault", "hqdefault", "mqdefault"):
        try:
            async with session.get(
                f"https://i.ytimg.com/vi/{vidid}/{q}.jpg",
                timeout=aiohttp.ClientTimeout(total=8),
            ) as r:
                if r.status == 200:
                    img = Image.open(io.BytesIO(await r.read())).convert("RGB")
                    if img.width > 200:
                        return img
        except Exception:
            continue
    return None


async def get_thumb(videoid, *args, title=None, artist=None, duration=None, **kwargs):
    """Blur-background now-playing thumbnail banata hai. Fail => YouTube thumb URL.

    Purane code ke saare call styles chalte hain: get_thumb(vidid),
    get_thumb(vidid, user_id), get_thumb(vidid, a, b, c ...) -- extra args ignore.
    """
    videoid = str(videoid)
    title = title if isinstance(title, str) else None
    artist = artist if isinstance(artist, str) else None
    duration = duration if isinstance(duration, str) else None
    fallback = f"https://i.ytimg.com/vi/{videoid}/hqdefault.jpg"
    path = f"cache/{videoid}_np.jpg"
    if os.path.isfile(path):
        return path
    try:
        if not (title and artist and duration):
            from py_yt import VideosSearch

            res = await VideosSearch(
                f"https://www.youtube.com/watch?v={videoid}", limit=1
            ).next()
            r = res["result"][0]
            title = title or r.get("title")
            artist = artist or (r.get("channel") or {}).get("name")
            duration = duration or r.get("duration")
        async with aiohttp.ClientSession() as session:
            cover = await _download(session, videoid)
        if cover is None:
            return fallback
        await asyncio.get_running_loop().run_in_executor(
            None, compose_thumb, cover, title, artist, duration, path
        )
        return path
    except Exception as e:
        print(f"[THUMB] fail: {type(e).__name__}: {e}")
        return fallback


gen_thumb = get_thumb  # purane naam se bhi chale
