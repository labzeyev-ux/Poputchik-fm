#!/usr/bin/env python3
"""Видеоряд по сюжетам: на каждую строку сценария свой кадр (фото, карта, карточка).

Запуск: python scripts/make_visuals.py issues/ПАПКА out/audio.wav out
Нужен issues/ПАПКА/visuals.json — список кадров, по одному на строку script.txt:
  {"type": "photo", "file": "img/merz.jpg", "caption": "...", "credit": "Фото: ..., CC BY 4.0"}
  {"type": "map",   "country": "Germany", "points": [["Арнсберг", 51.40, 8.06]], "caption": "..."}
  {"type": "card",  "kicker": "НЕФТЬ BRENT", "big": "91,70 $", "sub": "за баррель · −1 %", "caption": "..."}
  {"type": "email", "sender": "...", "subject": "...", "body": ["...", "..."], "caption": "..."}
  {"type": "word",  "word": "...", "parts": ["Rindfleisch", "..."], "sub": "...", "caption": "..."}
  {"type": "cover"}  — обложка выпуска (out/cover.png)
Фото берём только с явной свободной лицензией; источник и лицензия обязательно в "credit".
"""
import glob, json, os, re, subprocess, sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

issue, audio, out = sys.argv[1], sys.argv[2], (sys.argv[3] if len(sys.argv) > 3 else "out")
W, H, FPS = 1920, 1080, 25
JINGLE = 15.4          # джингл 15 с + пауза 0,4 с (как в make_issue.py)
GOLD, NAVY, WHITE, PALE = (255, 184, 0), (16, 26, 66), (255, 255, 255), (200, 210, 240)

lines = [l.strip() for l in open(f"{issue}/script.txt", encoding="utf-8") if l.strip()]
meta = json.load(open(f"{issue}/meta.json", encoding="utf-8"))
vis = json.load(open(f"{issue}/visuals.json", encoding="utf-8"))
assert len(vis) == len(lines), f"visuals.json: {len(vis)} кадров, а строк в сценарии {len(lines)}"
os.makedirs(f"{out}/frames", exist_ok=True)

def font(s, bold=True):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    return ImageFont.truetype(glob.glob(f"/usr/share/fonts/**/{name}", recursive=True)[0], s)

def bg():
    im = Image.new("RGB", (W, H)); d = ImageDraw.Draw(im)
    for y in range(H):
        d.line([(0, y), (W, y)], fill=(int(14 + 40*y/H), 24 + int(30*y/H), 60 + int(60*y/H)))
    d.rectangle([0, 0, W, 12], fill=GOLD)
    return im

def wrap(d, text, f, width):
    words, rows, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=f) <= width: cur = t
        else: rows.append(cur); cur = w
    if cur: rows.append(cur)
    return rows

def lower_third(im, caption, credit=None):
    d = ImageDraw.Draw(im, "RGBA")
    if caption:
        f = font(46); rows = wrap(d, caption, f, W - 260)[:2]
        h = 40 + 60 * len(rows)
        d.rectangle([0, H - h - 60, W, H - 60], fill=(10, 16, 40, 225))
        d.rectangle([0, H - h - 60, 18, H - 60], fill=GOLD)
        for i, r in enumerate(rows):
            d.text((70, H - h - 40 + 60*i), r, font=f, fill=WHITE)
    d.rectangle([0, H - 60, W, H], fill=(10, 16, 40, 255))
    d.text((70, H - 46), "ГЛАВНОЕ ЗА ДЕНЬ", font=font(28), fill=GOLD)
    if credit:
        f = font(22, bold=False)
        d.text((W - 40 - d.textlength(credit, font=f), H - 42), credit, font=f, fill=PALE)
    return im

def photo(v):
    src = Image.open(f"{issue}/{v['file']}").convert("RGB")
    # фон — размытая копия, сам снимок целиком, без обрезки и без изменений
    back = src.resize((W, H)).filter(ImageFilter.GaussianBlur(40))
    back = Image.blend(back, Image.new("RGB", (W, H), (8, 12, 30)), 0.45)
    s = min(W / src.width, (H - 60) / src.height)
    fg = src.resize((int(src.width * s), int(src.height * s)), Image.LANCZOS)
    back.paste(fg, ((W - fg.width) // 2, (H - 60 - fg.height) // 2))
    return back

def project(lon, lat, box, bounds):
    (x0, y0, x1, y1), (lo0, la0, lo1, la1) = box, bounds
    return x0 + (lon - lo0) / (lo1 - lo0) * (x1 - x0), y1 - (lat - la0) / (la1 - la0) * (y1 - y0)

def mapcard(v):
    world = json.load(open("assets/maps/countries.json", encoding="utf-8"))
    im = bg(); d = ImageDraw.Draw(im)
    poly = world[v["country"]]
    xs = [p[0] for ring in poly for p in ring]; ys = [p[1] for ring in poly for p in ring]
    if v.get("bounds"): lo0, la0, lo1, la1 = v["bounds"]
    else:
        lo0, lo1, la0, la1 = min(xs) - 1, max(xs) + 1, min(ys) - 0.7, max(ys) + 0.7
    # равные пропорции по широте
    import math
    k = math.cos(math.radians((la0 + la1) / 2))
    bw, bh = (lo1 - lo0) * k, la1 - la0
    s = min(1300 / bw, 760 / bh); cw, ch = bw * s, bh * s
    box = (W/2 - cw/2 + 200, 110 + (800 - ch) / 2, W/2 + cw/2 + 200, 110 + (800 - ch) / 2 + ch)
    bounds = (lo0, la0, lo1, la1)
    for name, rings in world.items():
        for ring in rings:
            pts = [project(x, y, box, bounds) for x, y in ring]
            if name == v["country"]: d.polygon(pts, fill=(44, 64, 130), outline=GOLD, width=4)
            elif any(lo0 - 5 < x < lo1 + 5 and la0 - 5 < y < la1 + 5 for x, y in ring):
                d.polygon(pts, fill=(28, 38, 82), outline=(70, 85, 140), width=2)
    for name, lat, lon in v.get("points", []):
        x, y = project(lon, lat, box, bounds)
        d.ellipse([x-18, y-18, x+18, y+18], fill=GOLD, outline=WHITE, width=4)
        d.text((x + 30, y - 30), name, font=font(54), fill=WHITE, stroke_width=4, stroke_fill=NAVY)
    d.text((80, 60), v.get("title", ""), font=font(64), fill=WHITE)
    return im, "Карта: Natural Earth (общественное достояние)"

def card(v):
    im = bg(); d = ImageDraw.Draw(im)
    d.text((140, 200), v["kicker"], font=font(64), fill=GOLD)
    d.text((140, 320), v["big"], font=font(210), fill=WHITE)
    y = 600
    for r in wrap(d, v.get("sub", ""), font(60, False), W - 280):
        d.text((140, y), r, font=font(60, False), fill=PALE); y += 80
    return im, v.get("credit")

def email(v):
    im = bg(); d = ImageDraw.Draw(im)
    x0, y0, x1, y1 = 260, 90, W - 260, 880
    d.rounded_rectangle([x0, y0, x1, y1], 24, fill=(246, 247, 250))
    d.rounded_rectangle([x0, y0, x1, y0 + 90], 24, fill=(225, 229, 238))
    d.rectangle([x0, y0 + 60, x1, y0 + 90], fill=(225, 229, 238))
    d.text((x0 + 40, y0 + 22), "Входящие", font=font(40), fill=(60, 70, 90))
    d.text((x0 + 40, y0 + 130), "От: " + v["sender"], font=font(38, False), fill=(60, 70, 90))
    d.text((x0 + 40, y0 + 190), v["subject"], font=font(46), fill=(20, 24, 40))
    y = y0 + 290
    for para in v["body"]:
        for r in wrap(d, para, font(38, False), x1 - x0 - 80):
            d.text((x0 + 40, y), r, font=font(38, False), fill=(40, 46, 60)); y += 52
        y += 20
    if v.get("button"):
        d.rounded_rectangle([x0 + 40, y, x0 + 560, y + 80], 12, fill=(40, 90, 200))
        d.text((x0 + 80, y + 18), v["button"], font=font(38), fill=WHITE)
    # штамп «фишинг»
    st = Image.new("RGBA", (760, 200), (0, 0, 0, 0)); sd = ImageDraw.Draw(st)
    sd.rounded_rectangle([6, 6, 754, 194], 20, outline=(220, 30, 30, 255), width=14)
    sd.text((60, 34), "ФИШИНГ!", font=font(130), fill=(220, 30, 30, 255))
    st = st.rotate(14, expand=True)
    im.paste(st, (x1 - st.width + 60, y0 + 330), st)
    return im, "Образец письма составлен редакцией"

def word(v):
    im = bg(); d = ImageDraw.Draw(im)
    d.text((120, 120), "СЛОВО ДНЯ", font=font(64), fill=GOLD)
    f = font(90); x, y = 120, 260
    for i, p in enumerate(v["parts"]):
        w = d.textlength(p, font=f)
        if x + w > W - 120: x, y = 120, y + 130
        d.text((x, y), p, font=f, fill=WHITE if i % 2 == 0 else GOLD); x += w
    y += 170
    for r in wrap(d, v.get("sub", ""), font(56, False), W - 240):
        d.text((120, y), r, font=font(56, False), fill=PALE); y += 76
    return im, None

def frame(v):
    t = v["type"]
    if t == "cover": return Image.open(f"{out}/cover.png").convert("RGB"), None, False
    if t == "photo": return photo(v), v["credit"], True
    if t == "map": im, c = mapcard(v); return im, c, False
    if t == "card": im, c = card(v); return im, c, False
    if t == "email": im, c = email(v); return im, c, False
    if t == "word": im, c = word(v); return im, c, False
    sys.exit(f"неизвестный тип кадра: {t}")

# --- тайминг: длина каждой строки пропорциональна числу букв, границы — на ближайшей паузе в речи
dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", audio],
                           capture_output=True, text=True, check=True).stdout)
log = subprocess.run(["ffmpeg", "-i", audio, "-af", "silencedetect=noise=-38dB:d=0.25", "-f", "null", "-"],
                     capture_output=True, text=True).stderr
st = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", log)]
en = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", log)]
pauses = [(a + b) / 2 for a, b in zip(st, en) if JINGLE < a < dur - JINGLE]
s0, s1 = JINGLE, dur - JINGLE
total = sum(len(l) for l in lines); cuts, acc = [0.0], 0
for l in lines[:-1]:
    acc += len(l); t = s0 + (s1 - s0) * acc / total
    near = [p for p in pauses if abs(p - t) < 4 and p > cuts[-1] + 2]
    cuts.append(min(near, key=lambda p: abs(p - t)) if near else t)
cuts.append(dur)

segs = []
for i, v in enumerate(vis):
    im, credit, zoom = frame(v)
    if v["type"] != "cover": im = lower_third(im, v.get("caption"), credit)
    p = f"{out}/frames/{i:02d}.png"; im.save(p)
    a, b = cuts[i], cuts[i + 1]; n = max(1, round((b - a) * FPS))
    seg = f"{out}/frames/{i:02d}.mp4"
    vf = (f"scale=2112:1188,zoompan=z='min(1+0.00025*on,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={W}x{H}:fps={FPS}"
          if zoom else f"fps={FPS}")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", p, "-frames:v", str(n), "-vf", vf,
                    "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", "-r", str(FPS), seg], check=True)
    segs.append(seg); print(f"кадр {i+1}/{len(vis)}: {b-a:.1f} с", flush=True)

open(f"{out}/frames/list.txt", "w").write("".join(f"file '{os.path.basename(s)}'\n" for s in segs))
subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", f"{out}/frames/list.txt", "-i", audio,
                "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-ar", "48000", "-shortest",
                f"{out}/video.mp4"], check=True)
# список источников для описания видео
credits = sorted({v["credit"] for v in vis if v.get("credit")})
open(f"{out}/credits.txt", "w", encoding="utf-8").write("\n".join(credits) + "\n")
print("готово", flush=True)
