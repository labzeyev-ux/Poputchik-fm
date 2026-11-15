#!/usr/bin/env python3
"""Сборка выпуска «Попутчик FM»: сценарий -> озвучка Gemini -> джингл -> обложка -> видео."""
import base64, json, os, subprocess, sys, time, glob
import numpy as np, requests
from PIL import Image, ImageDraw, ImageFont

SR = 24000
KEY = os.environ["GEMINI_API_KEY"]
MODEL = os.environ.get("TTS_MODEL", "gemini-3.8-flash-tts")
N1, N2 = "Анна", "Максим"
V1, V2 = "Kore", "Charon"

issue = sys.argv[1]
out = sys.argv[2] if len(sys.argv) > 2 else "out"
os.makedirs(out, exist_ok=True)
lines = [l.strip() for l in open(f"{issue}/script.txt", encoding="utf-8") if l.strip()]
meta = json.load(open(f"{issue}/meta.json", encoding="utf-8"))

def chunk(lines, limit=2500):
    res, cur, n = [], [], 0
    for l in lines:
        if cur and n + len(l) > limit:
            res.append(cur); cur, n = [], 0
        cur.append(l); n += len(l)
    if cur: res.append(cur)
    return res

def tts(chunk_lines):
    parts, last = [], N1
    for l in chunk_lines:
        sp, t = None, l
        if l.startswith(N1 + ":"): sp, t = N1, l[len(N1)+1:]
        elif l.startswith(N2 + ":"): sp, t = N2, l[len(N2)+1:]
        else: sp = last
        last = sp; t = t.strip()
        if t: parts.append({"text": t, "speech_metadata": {"speaker": sp}})
    body = {"contents": [{"parts": parts}],
            "generationConfig": {"responseModalities": ["AUDIO"],
                "speechConfig": {"multiSpeakerVoiceConfig": {"speakerVoiceConfigs": [
                    {"speaker": N1, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": V1}}},
                    {"speaker": N2, "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": V2}}}]}}}}
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent?key={KEY}"
    for attempt in range(6):
        r = requests.post(url, json=body, timeout=300)
        if r.status_code == 200:
            try:
                d = r.json()["candidates"][0]["content"]["parts"][0]["inlineData"]["data"]
                return np.frombuffer(base64.b64decode(d), dtype="<i2").astype(np.float32) / 32768
            except Exception as e:
                print("bad response", str(r.text)[:300], file=sys.stderr)
        elif r.status_code in (400, 403, 404):
            sys.exit(f"TTS error {r.status_code}: {r.text[:500]}")
        else:
            print(f"retry {attempt}: {r.status_code}", file=sys.stderr)
        time.sleep(8 * (attempt + 1))
    sys.exit("TTS failed after retries")

chunks = chunk(lines)
print(f"{len(chunks)} частей", flush=True)
speech = []
for i, c in enumerate(chunks, 1):
    print(f"озвучка {i}/{len(chunks)}", flush=True)
    a = tts(c)
    rms = np.sqrt(np.mean(a**2)) or 1
    speech.append(a * (0.11 / rms))
    speech.append(np.zeros(int(SR*0.25), dtype=np.float32))
speech = np.concatenate(speech)

def load_jingle(seconds=15):
    raw = subprocess.run(["ffmpeg","-v","error","-i","assets/jingle.wav","-t",str(seconds),"-ac","1","-ar",str(SR),"-f","f32le","-"],
                         capture_output=True, check=True).stdout
    j = np.frombuffer(raw, dtype="<f4").copy()
    n = len(j); fi, fo = int(SR*0.3), int(SR*2.5)
    j[:fi] *= np.linspace(0, 1, fi); j[-fo:] *= np.linspace(1, 0, fo)
    return j * 0.5

def load_song(path):
    raw = subprocess.run(["ffmpeg","-v","error","-i",path,"-ac","1","-ar",str(SR),"-f","f32le","-"],
                         capture_output=True, check=True).stdout
    j = np.frombuffer(raw, dtype="<f4").copy()
    fi, fo = int(SR*0.3), int(SR*3)
    j[:fi] *= np.linspace(0, 1, fi); j[-fo:] *= np.linspace(1, 0, fo)
    return j / (np.abs(j).max() or 1) * 0.5

jingle = load_jingle()
gap = np.zeros(int(SR*0.4), dtype=np.float32)
# в конце выпуска: песня канала (assets/song.mp3), если она есть, иначе джингл
song_path = next(iter(glob.glob("assets/song.*")), None)
ending = load_song(song_path) if song_path else jingle
full = np.concatenate([jingle, gap, speech, gap, ending])
pcm = (np.clip(full, -1, 1) * 32767).astype("<i2").tobytes()
open(f"{out}/raw.pcm", "wb").write(pcm)
subprocess.run(["ffmpeg","-y","-v","error","-f","s16le","-ar",str(SR),"-ac","1","-i",f"{out}/raw.pcm",
                "-af","loudnorm=I=-16:TP=-1.5:LRA=7", f"{out}/audio.wav"], check=True)
os.remove(f"{out}/raw.pcm")

# обложка 1920x1080
def font(s):
    p = (glob.glob("/usr/share/fonts/**/DejaVuSans-Bold.ttf", recursive=True) or [None])[0]
    return ImageFont.truetype(p, s)
W, H = 1920, 1080
im = Image.new("RGB", (W, H)); d = ImageDraw.Draw(im)
for y in range(H):
    c = int(14 + 40*y/H); d.line([(0, y), (W, y)], fill=(c, 24+int(30*y/H), 60+int(60*y/H)))
d.rectangle([0, 0, W, 16], fill=(255, 184, 0))
d.text((120, 120), "ПОПУТЧИК FM", font=font(150), fill=(255, 255, 255))
d.text((120, 300), "Новостной выпуск", font=font(78), fill=(255, 184, 0))
d.text((120, 400), meta["date_line"], font=font(56), fill=(220, 230, 255))
y = 540
for t in meta["bullets"][:6]:
    d.ellipse([125, y+16, 147, y+38], fill=(255, 184, 0)); d.text((170, y), t, font=font(50), fill=(255, 255, 255)); y += 76
d.text((120, 1000), "Радио для тех, кто за рулём · голоса ведущих созданы ИИ", font=font(34), fill=(170, 185, 220))
im.save(f"{out}/cover.png")

subprocess.run(["ffmpeg","-y","-v","error","-loop","1","-framerate","2","-i",f"{out}/cover.png","-i",f"{out}/audio.wav",
                "-c:v","libx264","-tune","stillimage","-pix_fmt","yuv420p","-r","2","-c:a","aac","-b:a","128k","-shortest",
                f"{out}/video.mp4"], check=True)
json.dump(meta, open(f"{out}/meta.json", "w", encoding="utf-8"), ensure_ascii=False, indent=2)
print("готово", flush=True)
