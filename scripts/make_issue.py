#!/usr/bin/env python3
"""Сборка выпуска: сценарий -> озвучка Gemini (по сюжетам) -> видео под каждый сюжет
(Wikimedia Commons, только лицензии с разрешённым коммерческим использованием)
-> плашки рубрики/заголовка, карточки курсов -> обложка -> video.mp4.

meta.json:
  show, subtitle, date_line, footer, bullets, title, description, tags
  speakers: [["Имя","Голос"], ...]  (1 ведущий или 2)
  ending: song | jingle | none
  segments: [ {rubric, headline, files:[...], queries:[...], card:[строки], card_color}, ... ]
            по одному на каждую строку script.txt (необязательно)
"""
import base64, glob, html, json, os, re, subprocess, sys, time
import numpy as np, requests
from PIL import Image, ImageDraw, ImageFont

SR = 24000
FPS = 25
W, H = 1920, 1080
KEY = os.environ.get("GEMINI_API_KEY", "")
MODEL = os.environ.get("TTS_MODEL", "gemini-3.8-flash-tts")
UA = "NewsVideoBuilder/2.1 (https://www.mediawiki.org/wiki/API:Etiquette) python-requests/2"
COMMONS = "https://commons.wikimedia.org/w/api.php"

issue = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else "out"
os.makedirs(out, exist_ok=True)
work = os.path.join(out, "work"); os.makedirs(work, exist_ok=True)
lines = [l.strip() for l in open(f"{issue}/script.txt", encoding="utf-8") if l.strip()]
meta = json.load(open(f"{issue}/meta.json", encoding="utf-8"))
SEGS = meta.get("segments") or []
if SEGS and len(SEGS) != len(lines):
    print(f"ВНИМАНИЕ: segments={len(SEGS)}, строк={len(lines)} — лишнее/недостающее заполню по умолчанию", flush=True)
SEGS = (SEGS + [{}] * len(lines))[:len(lines)]

SPK = meta.get("speakers") or [["Анна", "Kore"], ["Максим", "Charon"]]
VOICE = {n: v for n, v in SPK}
SHOW = meta.get("show", "ПОПУТЧИК FM")
SHORT_DATE = meta.get("short_date") or (re.search(r"\d{4}-(\d\d)-(\d\d)", os.path.basename(issue.rstrip("/"))) and
             "{2}.{1}".format(*re.search(r"(\d{4})-(\d\d)-(\d\d)", os.path.basename(issue.rstrip("/"))).groups())) or ""

def font(s, bold=True):
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    p = (glob.glob(f"/usr/share/fonts/**/{name}", recursive=True) or [None])[0]
    return ImageFont.truetype(p, s)

def run(cmd, timeout=900):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if r.returncode != 0:
        raise RuntimeError(" ".join(cmd[:6]) + " ...\n" + r.stderr[-1500:])
    return r

# ---------------------------------------------------------------- озвучка
# Озвучка идёт крупными частями (мало запросов к Gemini), границы сюжетов ищем по паузам.
# Готовая речь кэшируется (cache/speech.wav + speech.json) и при пересборке не озвучивается заново.
import hashlib
CACHE = os.environ.get("SPEECH_CACHE", "cache")

def split_speaker(line):
    for n, _ in SPK:
        if line.startswith(n + ":"):
            return n, line[len(n) + 1:].strip()
    return None, line

def chunk(ls, limit=2500):
    res, cur, n = [], [], 0
    for l in ls:
        if cur and n + len(l) > limit:
            res.append(cur); cur, n = [], 0
        cur.append(l); n += len(l)
    if cur: res.append(cur)
    return res

def tts(chunk_lines):
    parts, last = [], SPK[0][0]
    for l in chunk_lines:
        sp, t = split_speaker(l); sp = sp or last; last = sp
        if t: parts.append({"text": t, "speech_metadata": {"speaker": sp}})
    if len({p["speech_metadata"]["speaker"] for p in parts}) == 1:
        voice = VOICE.get(parts[0]["speech_metadata"]["speaker"], SPK[0][1])
        body = {"contents": [{"parts": [{"text": "\n".join(p["text"] for p in parts)}]}],
                "generationConfig": {"responseModalities": ["AUDIO"],
                    "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}}}}}
    else:
        body = {"contents": [{"parts": parts}],
                "generationConfig": {"responseModalities": ["AUDIO"],
                    "speechConfig": {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": [
                        {"speaker": n, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": v}}} for n, v in SPK[:2]]}}}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}"
    for attempt in range(8):
        try:
            r = requests.post(url, json=body, timeout=300)
        except requests.RequestException as e:
            print("сеть:", e, file=sys.stderr); time.sleep(15 * (attempt + 1)); continue
        if r.status_code == 200:
            try:
                d = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                return np.frombuffer(base64.b64decode(d), dtype="<i2").astype(np.float32) / 32768
            except Exception:
                print("bad response", r.text[:300], file=sys.stderr)
        elif r.status_code in (400, 403, 404):
            sys.exit(f"TTS error {r.status_code}: {r.text[:500]}")
        else:
            print(f"retry {attempt}: {r.status_code} {r.text[:200]}", file=sys.stderr)
        time.sleep(20 * (attempt + 1))
    sys.exit("TTS failed after retries (лимит Gemini?)")

if os.environ.get("FAKE_TTS"):  # локальная проверка без сети: «речь» с паузами между строками
    def tts(chunk_lines):
        out_ = []
        for l in chunk_lines:
            n = int(SR * len(l) / 15); t = np.arange(n) / SR
            out_.append((0.2 * np.sin(2 * np.pi * 220 * t) * (np.sin(2 * np.pi * 3 * t) > -0.6)).astype(np.float32))
            out_.append(np.zeros(int(SR * 0.6), dtype=np.float32))
        return np.concatenate(out_)

def load_audio(path, seconds=None, start=None):
    cmd = ["ffmpeg", "-v", "error"] + (["-ss", str(start)] if start else []) + ["-i", path] + \
          (["-t", str(seconds)] if seconds else []) + ["-ac", "1", "-ar", str(SR), "-f", "f32le", "-"]
    return np.frombuffer(subprocess.run(cmd, capture_output=True, check=True).stdout, dtype="<f4").copy()

def silences(a, win=0.02, min_len=0.22):
    """Список пауз (начало, конец) в отсчётах."""
    n = int(SR * win); m = len(a) // n
    if m == 0: return []
    e = np.sqrt(np.mean(a[:m * n].reshape(m, n) ** 2, axis=1))
    thr = max(0.006, np.percentile(e, 60) * 0.12)
    quiet = e < thr; res, st = [], None
    for i, q in enumerate(list(quiet) + [False]):
        if q and st is None: st = i
        if not q and st is not None:
            if (i - st) * win >= min_len: res.append((st * n, i * n))
            st = None
    return res

def align(a, ls):
    """Границы строк внутри аудио: по паузам, ближе всего к ожидаемому по числу букв месту."""
    sil = silences(a); bounds = [0]
    chars = [max(1, len(l)) for l in ls]
    for k in range(1, len(ls)):
        prev = bounds[-1]
        rate = (len(a) - prev) / sum(chars[k - 1:])
        exp = prev + chars[k - 1] * rate
        win = max(SR * 2.0, chars[k - 1] * rate * 0.35)
        best, score = None, None
        for s0, s1 in sil:
            mid = (s0 + s1) / 2
            if mid <= prev + SR * 1.0 or abs(mid - exp) > win: continue
            sc = (s1 - s0) / SR * 2.0 - abs(mid - exp) / SR * 0.25
            if score is None or sc > score: best, score = mid, sc
        bounds.append(int(best if best is not None else exp))
    bounds.append(len(a))
    return bounds

def _w(t):
    return re.sub(r"[^0-9a-zа-яё]+", "", t.lower().replace("ё", "е"))

def match_bounds(words, ls, total_len, sil):
    """words: [(время_c, слово)] из распознавания; ls: строки сценария.
    Сопоставляем весь текст сценария с распознанным (difflib) и берём время первого слова каждой строки."""
    import difflib
    sw, starts = [], []
    for l in ls:
        starts.append(len(sw))
        sw += [_w(x) for x in split_speaker(l)[1].split() if _w(x)]
    ww = [w for _, w in words]
    sm = difflib.SequenceMatcher(None, sw, ww, autojunk=False)
    m = {}
    for blk in sm.get_matching_blocks():
        for d in range(blk.size): m[blk.a + d] = words[blk.b + d][0]
    print(f"сопоставлено слов: {len(m)} из {len(sw)}", flush=True)
    bounds, miss = [0], 0
    for k in range(1, len(ls)):
        s0 = starts[k]; t = None
        for j in range(s0, min(s0 + 8, len(sw))):
            if j in m: t = m[j] - (j - s0) * 0.38; break
        if t is None:
            for j in range(s0 - 1, max(s0 - 8, -1), -1):
                if j in m: t = m[j] + (s0 - j) * 0.38; break
        if t is None:
            miss += 1; x = None
        else:
            x = int(t * SR) - int(SR * 0.1)
            near = [(abs((p0 + p1) / 2 - x), (p0 + p1) // 2) for p0, p1 in sil if p1 >= x - SR * 1.0 and p0 <= x + SR * 0.3]
            if near: x = int(min(near)[1])
        if x is None or x <= bounds[-1] + SR:
            # нет опоры — делим по числу букв
            rest = sum(len(l) for l in ls[k - 1:])
            x = int(bounds[-1] + (total_len - bounds[-1]) * len(ls[k - 1]) / rest)
        bounds.append(x)
    bounds.append(total_len)
    return bounds, miss

def align_whisper(a, ls):
    """Точные границы: распознаём речь (faster-whisper) и сопоставляем со сценарием."""
    try:
        from faster_whisper import WhisperModel
    except Exception as e:
        print("whisper недоступен:", e, flush=True); return None
    try:
        model = WhisperModel(os.environ.get("WHISPER_MODEL", "small"), device="cpu", compute_type="int8")
        a16 = np.interp(np.arange(0, len(a), SR / 16000), np.arange(len(a)), a).astype(np.float32)  # whisper ждёт 16 кГц
        segs, _ = model.transcribe(a16, language="ru", word_timestamps=True, vad_filter=False,
                                   beam_size=1, condition_on_previous_text=False)
        words = [(w.start, _w(w.word)) for sg in segs for w in (sg.words or []) if _w(w.word)]
        print(f"whisper: распознано слов {len(words)}", flush=True)
    except Exception as e:
        print("whisper ошибка:", e, flush=True); return None
    if len(words) < 20: return None
    bounds, miss = match_bounds(words, ls, len(a), silences(a, min_len=0.12))
    if any(b1 - b0 < SR * 2 for b0, b1 in zip(bounds, bounds[1:])) or bounds[-2] >= len(a):
        print("whisper: границы не сходятся — беру паузы", flush=True); return None
    if miss > len(ls) // 3:
        print(f"whisper: нет опоры для {miss} строк — беру паузы", flush=True); return None
    print("границы по распознаванию речи: " + ", ".join(f"{b/SR:.1f}" for b in bounds[1:-1]), flush=True)
    return bounds

def norm(a):
    rms = np.sqrt(np.mean(a ** 2)) or 1
    return a * (0.11 / rms)

key = hashlib.sha256(json.dumps([lines, SPK, MODEL], ensure_ascii=False).encode()).hexdigest()[:16]
speech, bounds, method = None, None, "pauses"
try:
    c = json.load(open(f"{CACHE}/speech.json", encoding="utf-8"))
    if c.get("key") == key and os.path.exists(f"{CACHE}/speech.wav"):
        speech, bounds, method = load_audio(f"{CACHE}/speech.wav"), c["bounds"], c.get("method", "pauses")
        print(f"речь взята из кэша (озвучка не нужна), границы: {method}", flush=True)
        if method != "whisper":
            wb = align_whisper(speech, lines)
            if wb: bounds, method = wb, "whisper"
except Exception as e:
    print("кэш речи:", e, flush=True)
if speech is None and meta.get("reuse_audio") and os.path.exists(f"{CACHE}/legacy_audio.wav"):
    # речь из прошлой сборки (джингл 15 c + 0,4 c тишины в начале и в конце)
    full_old = load_audio(f"{CACHE}/legacy_audio.wav")
    speech = full_old[int(SR * 15.4): len(full_old) - int(SR * 15.4)]
    wb = align_whisper(speech, lines)
    bounds, method = (wb, "whisper") if wb else (align(speech, lines), "pauses")
    print(f"речь взята из прошлой сборки: {len(speech)/SR:.1f} c", flush=True)
if speech is None:
    chunks = chunk(lines)
    print(f"{len(chunks)} частей", flush=True)
    sp_parts, bounds, pos = [], [], 0
    for i, c in enumerate(chunks, 1):
        print(f"озвучка {i}/{len(chunks)}", flush=True)
        a = norm(tts(c))
        b = align(a, c)
        bounds += [pos + x for x in b[:-1]]
        sp_parts.append(a); pos += len(a)
        pz = np.zeros(int(SR * 0.3), dtype=np.float32); sp_parts.append(pz); pos += len(pz)
    bounds.append(pos)
    speech = np.concatenate(sp_parts)
    wb = align_whisper(speech, lines)
    if wb: bounds, method = wb, "whisper"
os.makedirs(f"{out}/cache", exist_ok=True)
sf = (np.clip(speech, -1, 1) * 32767).astype("<i2").tobytes()
open(f"{work}/speech.pcm", "wb").write(sf)
run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", f"{work}/speech.pcm", f"{out}/speech.wav"])
json.dump({"key": key, "bounds": [int(x) for x in bounds], "method": method}, open(f"{out}/speech.json", "w"))

def fade(j, fi, fo):
    j[:fi] *= np.linspace(0, 1, fi); j[-fo:] *= np.linspace(1, 0, fo); return j

jingle = fade(load_audio("assets/jingle.wav", 15), int(SR * 0.3), int(SR * 2.5)) * 0.5
song_path = next(iter(glob.glob("assets/song.*")), None)
end_mode = meta.get("ending", "song")
if end_mode == "none": ending = np.zeros(int(SR * 2), dtype=np.float32)
elif end_mode == "song" and song_path:
    s_ = fade(load_audio(song_path), int(SR * 0.3), int(SR * 3)); ending = s_ / (np.abs(s_).max() or 1) * 0.5
else: ending = jingle.copy()

if len(bounds) != len(lines) + 1 or any(b1 - b0 < SR for b0, b1 in zip(bounds, bounds[1:])) or bounds[-1] != len(speech):
    print("границы некорректны — делю по паузам заново", flush=True)
    bounds = align(speech, lines)
gap = np.zeros(int(SR * 0.4), dtype=np.float32)
off = len(jingle) + len(gap)
timeline = [((off + bounds[k]) / SR, (off + bounds[k + 1]) / SR) for k in range(len(lines))]
intro_end = timeline[0][0]
outro_start = (off + len(speech)) / SR
full = np.concatenate([jingle, gap, speech, gap, ending])
total = len(full) / SR
pcm = (np.clip(full, -1, 1) * 32767).astype("<i2").tobytes()
open(f"{work}/raw.pcm", "wb").write(pcm)
run(["ffmpeg", "-y", "-v", "error", "-f", "s16le", "-ar", str(SR), "-ac", "1", "-i", f"{work}/raw.pcm",
     "-af", "loudnorm=I=-16:TP=-1.5:LRA=7", "-ar", "48000", f"{out}/audio.wav"])
os.remove(f"{work}/raw.pcm"); os.remove(f"{work}/speech.pcm")
print(f"звук: {total:.1f} c, сюжетов {len(timeline)}: " + ", ".join(f"{b-a:.0f}" for a, b in timeline), flush=True)

# ---------------------------------------------------------------- видео с Commons
OK_LIC = re.compile(r"^(cc0|cc[- ]?zero|public domain|pd|pdm|cc[- ]by(-sa)?[- ]?\d(\.\d)?( [a-z]{2,3})?|attribution|attribution-sharealike)", re.I)
BAD_LIC = re.compile(r"\b(nc|nd|noncommercial|no derivatives|fair use|non-free)\b", re.I)
BAD_TITLE = re.compile(r"\.sbs\.|stereoscop|hitler|nazi|1939|reichstag speech|execution|corpse|beheading|porn|gameplay|minecraft|explained in|tutorial|vertical|unbranded", re.I)
session = requests.Session(); session.headers["User-Agent"] = UA
_last = [0.0]

def api(params):
    params = dict(params, format="json", formatversion=2)
    for a in range(6):
        wait = 1.2 - (time.time() - _last[0])
        if wait > 0: time.sleep(wait)
        _last[0] = time.time()
        try:
            r = session.get(COMMONS, params=params, timeout=40)
            if r.ok and r.text.startswith("{"): return r.json()
            print(f"  commons {r.status_code}, жду", flush=True)
        except requests.RequestException as e:
            print("  commons:", e, flush=True)
        time.sleep(6 * (a + 1))
    return {}

def clean(s):
    s = html.unescape(re.sub(r"<[^>]+>", " ", s or ""))
    return re.sub(r"\s+", " ", s).strip()

def info_of(page):
    vi = (page.get("videoinfo") or [{}])[0]
    em = vi.get("extmetadata", {})
    lic = clean(em.get("LicenseShortName", {}).get("value", ""))
    w, h, dur = vi.get("width") or 0, vi.get("height") or 0, vi.get("duration") or 0
    ders = vi.get("derivatives") or []
    best = None
    for want in (720, 480, 576, 1080, 360):
        for d in ders:
            if d.get("height") == want and ("webm" in d.get("type", "") or "mp4" in d.get("type", "")):
                best = d.get("src"); break
        if best: break
    if not best and (vi.get("mime", "").startswith("video/") or page["title"].lower().endswith((".webm", ".ogv", ".mp4"))):
        best = vi.get("url")
    artist = clean(em.get("Artist", {}).get("value", "")) or "неизвестный автор"
    artist = re.sub(r"(?i)this (video|file) is a work by .*", "", artist).strip() or "Wikimedia Commons"
    return {"title": page["title"], "lic": lic, "w": w, "h": h, "dur": dur, "src": best,
            "artist": artist[:60], "page": "https://commons.wikimedia.org/wiki/" + page["title"].replace(" ", "_"),
            "date": clean(em.get("DateTimeOriginal", {}).get("value", ""))[:10]}

def usable(c, need):
    if not c["src"] or not OK_LIC.search(c["lic"] or "") or BAD_LIC.search(c["lic"] or ""): return False
    if c["w"] < c["h"] * 1.2 or c["h"] < 360: return False
    if c["dur"] < min(5, need): return False
    if BAD_TITLE.search(c["title"]): return False
    return True

VIPROP = "url|size|mime|extmetadata|derivatives"
def by_titles(titles):
    titles = [t if t.startswith("File:") else "File:" + t for t in titles]
    if not titles: return []
    r = api({"action": "query", "titles": "|".join(titles[:20]), "prop": "videoinfo", "viprop": VIPROP})
    pages = {p["title"]: p for p in r.get("query", {}).get("pages", []) if "videoinfo" in p}
    norm = {n["from"]: n["to"] for n in r.get("query", {}).get("normalized", [])}
    return [info_of(pages[norm.get(t, t)]) for t in titles if norm.get(t, t) in pages]

def by_query(q, n=12):
    r = api({"action": "query", "generator": "search", "gsrsearch": f"{q} filetype:video", "gsrnamespace": 6,
             "gsrlimit": n, "prop": "videoinfo", "viprop": VIPROP})
    pages = sorted(r.get("query", {}).get("pages", []), key=lambda p: p.get("index", 99))
    return [info_of(p) for p in pages if "videoinfo" in p]

if os.environ.get("FAKE_CLIP"):
    def by_titles(titles): return []
    def by_query(q, n=12):
        return [{"title": f"File:{q} {i}.webm", "lic": "CC BY-SA 4.0", "w": 1280, "h": 720, "dur": 30, "src": os.environ["FAKE_CLIP"],
                 "artist": "Тестовый Автор", "page": "https://commons.wikimedia.org/wiki/x", "date": ""} for i in range(3)]

used = set()
def pick_clips(seg, total_need, k):
    cands = by_titles(seg.get("files", []))
    for q in seg.get("queries", []):
        if sum(1 for c in cands if usable(c, 4) and c["title"] not in used) >= k: break
        cands += by_query(q)
    res, seen = [], set()
    for c in cands:
        if c["title"] in used or c["title"] in seen or not usable(c, total_need / k): continue
        seen.add(c["title"]); res.append(c)
        if len(res) >= k: break
    for c in res: used.add(c["title"])
    return res

_dl_last = [0.0]
def download(url, dst):
    """Скачивает файл целиком одним запросом (так требует Wikimedia), с паузами и Retry-After."""
    if os.path.exists(dst) and os.path.getsize(dst) > 10000: return True
    for a in range(5):
        wait = 2.5 - (time.time() - _dl_last[0])
        if wait > 0: time.sleep(wait)
        _dl_last[0] = time.time()
        try:
            with session.get(url, stream=True, timeout=60) as r:
                if r.status_code == 200:
                    size = int(r.headers.get("content-length") or 0)
                    if size > 400_000_000:
                        print(f"  слишком большой файл ({size//1_000_000} МБ), пропускаю", flush=True); return False
                    with open(dst + ".part", "wb") as f:
                        for ch in r.iter_content(1 << 20): f.write(ch)
                    os.replace(dst + ".part", dst); return True
                ra = int(r.headers.get("retry-after", "0") or 0)
                print(f"  {r.status_code} от Wikimedia, жду {min(max(ra, 10 * (a + 1)), 180)} c", flush=True)
                time.sleep(min(max(ra, 10 * (a + 1)), 180))
        except requests.RequestException as e:
            print("  загрузка:", e, flush=True); time.sleep(10 * (a + 1))
    return False

def fetch(c, start, dur, dst):
    """Скачивает клип и вырезает нужный кусок 1920x1080."""
    local = os.path.join(work, "dl_" + hashlib.md5(c["src"].encode()).hexdigest()[:12] + os.path.splitext(c["src"].split("?")[0])[1])
    if c["src"].startswith("http"):
        if not download(c["src"], local): return 0
    else:
        local = c["src"]
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},setsar=1,fps={FPS},"
          f"eq=brightness=-0.04:saturation=1.05")
    try:
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}", "-t", f"{dur + 0.5:.2f}", "-i", local,
             "-an", "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", dst])
        got = float(run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", dst]).stdout or 0)
        return got if got >= 1.0 else 0
    except Exception as e:
        print("  обработка не удалась:", str(e)[-300:], flush=True)
        return 0

# ---------------------------------------------------------------- графика
YEL, WHITE = (255, 184, 0), (255, 255, 255)

def wrap(d, text, f, maxw):
    words, rows, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=f) <= maxw: cur = t
        else:
            if cur: rows.append(cur)
            cur = w_
    if cur: rows.append(cur)
    return rows

def overlay_png(path, seg, credit, card=None):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(im)
    # затемнение снизу для читаемости
    for y in range(H - 420, H):
        a = int(200 * ((y - (H - 420)) / 420) ** 1.4); d.line([(0, y), (W, y)], fill=(5, 10, 30, a))
    # бренд в углу
    f_b = font(34); tag = f"{SHOW}" + (f" · {SHORT_DATE}" if SHORT_DATE else "")
    tw = d.textlength(tag, font=f_b)
    d.rounded_rectangle([48, 44, 48 + tw + 44, 104], 12, fill=(10, 20, 55, 210))
    d.rectangle([48, 44, 58, 104], fill=YEL)
    d.text((76, 52), tag, font=f_b, fill=WHITE)
    if card:
        d.rectangle([0, 0, W, H], fill=(5, 10, 30, 120))
        f_c = font(110); rows = card["lines"]
        hh = 150 * len(rows) + 80; ww = max(d.textlength(r, font=f_c) for r in rows) + 160
        x0, y0 = (W - ww) / 2, (H - hh) / 2 - 80
        d.rounded_rectangle([x0, y0, x0 + ww, y0 + hh], 28, fill=(10, 20, 55, 230), outline=card["color"], width=6)
        for i, r in enumerate(rows):
            col = card["color"] if i == 0 else WHITE
            d.text((W / 2, y0 + 40 + 150 * i + 65), r, font=f_c, fill=col, anchor="mm")
    rub, head = (seg.get("rubric") or "").upper(), seg.get("headline") or ""
    y = H - 250
    if rub:
        f_r = font(40); rw = d.textlength(rub, font=f_r)
        d.rounded_rectangle([80, y - 70, 80 + rw + 48, y - 10], 10, fill=YEL)
        d.text((104, y - 63), rub, font=f_r, fill=(10, 20, 55))
    if head:
        f_h = font(60); rows = wrap(d, head, f_h, W - 200)[:2]
        if len(rows) == 2: y -= 10
        for i, r in enumerate(rows):
            d.text((80, y + i * 76), r, font=f_h, fill=WHITE, stroke_width=2, stroke_fill=(5, 10, 30))
    if credit:
        f_s = font(22, bold=False); cw = d.textlength(credit, font=f_s)
        d.text((W - 40 - cw, H - 44), credit, font=f_s, fill=(215, 222, 240))
    im.save(path)

def cover(path, bg=None):
    if bg and os.path.exists(bg):
        im = Image.open(bg).convert("RGB").resize((W, H))
        dk = Image.new("RGB", (W, H), (8, 16, 45)); im = Image.blend(im, dk, 0.62)
    else:
        im = Image.new("RGB", (W, H)); d0 = ImageDraw.Draw(im)
        for y in range(H):
            c = int(14 + 40 * y / H); d0.line([(0, y), (W, y)], fill=(c, 24 + int(30 * y / H), 60 + int(60 * y / H)))
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, 16], fill=YEL)
    f_t = font(150)
    while d.textlength(SHOW, font=f_t) > W - 240: f_t = font(f_t.size - 6)
    d.text((120, 120), SHOW, font=f_t, fill=WHITE)
    d.text((120, 300), meta.get("subtitle", "Новостной выпуск"), font=font(78), fill=YEL)
    d.text((120, 400), meta["date_line"], font=font(56), fill=(220, 230, 255))
    y = 540
    for t in meta.get("bullets", [])[:6]:
        d.ellipse([125, y + 16, 147, y + 38], fill=YEL); d.text((170, y), t, font=font(50), fill=WHITE); y += 76
    d.text((120, 1000), meta.get("footer", "Голоса ведущих созданы ИИ"), font=font(34), fill=(170, 185, 220))
    im.save(path)

# ---------------------------------------------------------------- сборка по сюжетам
def frames_between(a, b): return int(round(b * FPS)) - int(round(a * FPS))

parts, credits = [], []
def still_part(img, nframes, name, zoom=True):
    dst = f"{work}/{name}.mp4"
    vf = (f"scale={W*2}:{H*2},zoompan=z='min(zoom+0.0004,1.08)':d={nframes}:s={W}x{H}:fps={FPS}"
          if zoom else f"scale={W}:{H},fps={FPS}")
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", img, "-vf", vf, "-frames:v", str(nframes),
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS), dst])
    return dst

def overlay_part(src, png, nframes, name):
    dst = f"{work}/{name}.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-stream_loop", "-1", "-i", src, "-i", png,
         "-filter_complex", f"[0:v]fps={FPS},setpts=N/{FPS}/TB[v];[v][1:v]overlay=0:0:format=auto,format=yuv420p",
         "-frames:v", str(nframes), "-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-r", str(FPS), dst])
    return dst

fallback_bg = f"{work}/fallback.png"
cover(fallback_bg)
first_frame = None
seg_clips = []
for i, (seg, (t0, t1)) in enumerate(zip(SEGS, timeline)):
    dur = t1 - t0
    k = 1 if dur < 13 else (2 if dur < 28 else 3)
    k = min(k, int(seg.get("max_clips") or k))
    clips = pick_clips(seg, dur, k)
    print(f"сюжет {i+1}: {dur:.1f} c, клипов {len(clips)}: " + "; ".join(c["title"][5:60] for c in clips), flush=True)
    seg_clips.append(clips)

cover_bg = None
for i, (seg, (t0, t1), clips) in enumerate(zip(SEGS, timeline, seg_clips)):
    card = None
    if seg.get("card"):
        cl = seg["card"] if isinstance(seg["card"], list) else [seg["card"]]
        card = {"lines": cl, "color": seg.get("card_color", "#FFB800")}
    total_f = frames_between(t0, t1)
    pieces_ok = []
    if clips:
        each = total_f // len(clips)
        for j, c in enumerate(clips):
            nf = each if j < len(clips) - 1 else total_f - each * (len(clips) - 1)
            need = nf / FPS
            start = 0.0 if c["dur"] <= need + 2 else min(c["dur"] * 0.15, c["dur"] - need - 1)
            raw = f"{work}/s{i:02d}_{j}_raw.mp4"
            got = fetch(c, start, need, raw)
            if got:
                pieces_ok.append((c, raw, nf))
                credits.append({"segment": i + 1, "headline": seg.get("headline", ""), "file": c["title"],
                                "author": c["artist"], "license": c["lic"], "url": c["page"]})
            else:
                print(f"  не скачался: {c['title']}", flush=True)
    if pieces_ok and len(pieces_ok) < len(clips):  # перераспределить кадры
        each = total_f // len(pieces_ok)
        pieces_ok = [(c, r, each if j < len(pieces_ok) - 1 else total_f - each * (len(pieces_ok) - 1))
                     for j, (c, r, _) in enumerate(pieces_ok)]
    if not pieces_ok:
        png = f"{work}/s{i:02d}_ov.png"; overlay_png(png, seg, "", card)
        bgc = Image.open(fallback_bg).convert("RGBA"); bgc.alpha_composite(Image.open(png)); bgc.convert("RGB").save(f"{work}/s{i:02d}_still.png")
        parts.append(still_part(f"{work}/s{i:02d}_still.png", total_f, f"s{i:02d}"))
        continue
    for j, (c, raw, nf) in enumerate(pieces_ok):
        lic = c["lic"].replace("Public domain", "общественное достояние")
        credit = f"Видео: {c['artist']} · {lic} · Wikimedia Commons"
        png = f"{work}/s{i:02d}_{j}_ov.png"; overlay_png(png, seg, credit, card)
        parts.append(overlay_part(raw, png, nf, f"s{i:02d}_{j}"))
        if cover_bg is None:
            cover_bg = f"{work}/cover_bg.png"
            run(["ffmpeg", "-y", "-v", "error", "-ss", "1", "-i", raw, "-frames:v", "1", cover_bg])

# заставка и финал
cover(f"{out}/cover.png", cover_bg)
intro_f = int(round(intro_end * FPS))
outro_f = int(round(total * FPS)) - int(round(outro_start * FPS))
parts = [still_part(f"{out}/cover.png", intro_f, "intro")] + parts + [still_part(f"{out}/cover.png", max(outro_f, 1), "outro")]

with open(f"{work}/list.txt", "w") as f:
    for p in parts: f.write(f"file '{os.path.abspath(p)}'\n")
run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", f"{work}/list.txt", "-c", "copy", f"{work}/video_noaudio.mp4"])
run(["ffmpeg", "-y", "-v", "error", "-i", f"{work}/video_noaudio.mp4", "-i", f"{out}/audio.wav",
     "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", "-movflags", "+faststart", f"{out}/video.mp4"])

# контрольный лист: по кадру из середины каждого сюжета
thumbs = []
for i, (t0, t1) in enumerate(timeline):
    p = f"{work}/t{i:02d}.png"
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{(t0 + t1) / 2:.2f}", "-i", f"{out}/video.mp4", "-frames:v", "1", "-vf", "scale=480:270", p])
    thumbs.append(p)
cols = 4; rows_n = (len(thumbs) + cols - 1) // cols
sheet = Image.new("RGB", (cols * 480, rows_n * 270), (0, 0, 0))
for i, p in enumerate(thumbs):
    sheet.paste(Image.open(p), ((i % cols) * 480, (i // cols) * 270))
sheet.save(f"{out}/contact.jpg", quality=85)

# авторы видео (лицензии CC BY / CC BY-SA требуют указания)
seen, cred_lines = set(), []
for c in credits:
    if c["file"] in seen: continue
    seen.add(c["file"])
    cred_lines.append(f"{c['author']} — {c['license']} — {c['url']}")
open(f"{out}/credits.txt", "w", encoding="utf-8").write("\n".join(cred_lines) + "\n")
desc = meta.get("description", "")
if cred_lines:
    desc = desc.rstrip() + "\n\nВидео: Wikimedia Commons (свободные лицензии):\n" + "\n".join("— " + l for l in cred_lines)
meta_out = dict(meta, description_with_credits=desc[:4900], video_credits=credits)
json.dump(meta_out, open(f"{out}/meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print(f"готово: {total:.1f} c, клипов {len(credits)}", flush=True)
