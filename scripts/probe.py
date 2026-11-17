"""Временная проба: кадры из роликов-кандидатов Wikimedia Commons."""
import requests, re, time, os, subprocess, html
from PIL import Image, ImageDraw, ImageFont
UA = {"User-Agent": "NewsVideoBuilder/2.1 (https://www.mediawiki.org/wiki/API:Etiquette) python-requests/2"}
API = "https://commons.wikimedia.org/w/api.php"
os.makedirs("out", exist_ok=True)
F = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", 14)
def api(p):
    p = dict(p, format="json", formatversion=2)
    for a in range(5):
        r = requests.get(API, params=p, headers=UA, timeout=30)
        if r.ok and r.text.startswith("{"): return r.json()
        time.sleep(5 * (a + 1))
    return {}
VP = "url|size|extmetadata|derivatives"
def search(q, n=8):
    r = api({"action":"query","generator":"search","gsrsearch":f"{q} filetype:video","gsrnamespace":6,"gsrlimit":n,"prop":"videoinfo","viprop":VP})
    return sorted(r.get("query",{}).get("pages",[]), key=lambda p: p.get("index",99))
def ok(pg):
    vi=(pg.get("videoinfo") or [{}])[0]; lic=vi.get("extmetadata",{}).get("LicenseShortName",{}).get("value","")
    w,h,d=vi.get("width") or 0, vi.get("height") or 0, vi.get("duration") or 0
    return w>=h*1.2 and h>=480 and d>=6 and not re.search(r"\b(NC|ND)\b",lic) and ".sbs." not in pg["title"]
def src(vi):
    for want in (480,360,720):
        for d in vi.get("derivatives",[]):
            if d.get("height")==want and "webm" in d.get("type",""): return d["src"]
    return vi.get("url")
GROUPS = {
 "crime": ["Polizei Einsatzfahrzeug","Polizeiauto","Streifenwagen Polizei Deutschland","police car blue lights Germany","Mönchengladbach"],
 "bank": ["Commerzbank Tower","Frankfurt Bankenviertel","Geldautomat","ATM cash machine","smartphone screen app"],
 "admin": ["Hamburg Hafencity","Düsseldorf Medienhafen","office desk paperwork","Elbphilharmonie Hamburg"],
 "outro": ["Berlin skyline evening","Brandenburger Tor","Reichstag dome","Berlin Spree evening"],
}
lines=[]
for g, qs in GROUPS.items():
    tiles=[]
    seen=set()
    for q in qs:
        for pg in search(q):
            if pg["title"] in seen or not ok(pg): continue
            seen.add(pg["title"]); vi=pg["videoinfo"][0]; d=vi.get("duration") or 10
            u=src(vi)
            if not u: continue
            time.sleep(2.5)
            loc=f"/tmp/c{len(tiles)}.webm"
            try:
                with requests.get(u, headers=UA, stream=True, timeout=60) as r:
                    if r.status_code!=200 or int(r.headers.get("content-length") or 0)>120_000_000: continue
                    with open(loc,"wb") as f:
                        for ch in r.iter_content(1<<20): f.write(ch)
            except Exception: continue
            fr=[]
            for k,frac in enumerate((0.15,0.45,0.75)):
                p=f"/tmp/f{len(tiles)}_{k}.jpg"
                subprocess.run(["ffmpeg","-v","error","-y","-ss",str(d*frac),"-i",loc,"-frames:v","1","-vf","scale=320:180:force_original_aspect_ratio=decrease,pad=320:180",p])
                if os.path.exists(p): fr.append(p)
            if not fr: continue
            idx=len(tiles); tiles.append((pg["title"][5:], fr))
            lines.append(f"{g}#{idx} | {pg['title'][5:]} | {round(d)}s | {vi.get('extmetadata',{}).get('LicenseShortName',{}).get('value','')}")
            if len(tiles)>=12: break
        if len(tiles)>=12: break
    W=3*320; H=len(tiles)*200
    if not tiles: continue
    im=Image.new("RGB",(W,H),(0,0,0)); dr=ImageDraw.Draw(im)
    for i,(t,fr) in enumerate(tiles):
        for k,p in enumerate(fr): im.paste(Image.open(p),(k*320,i*200))
        dr.rectangle([0,i*200+180,W,i*200+200],fill=(0,0,0)); dr.text((4,i*200+182),f"#{i} {t[:110]}",font=F,fill=(255,255,0))
    im.save(f"out/{g}.jpg",quality=80)
open("out/list.txt","w").write("\n".join(lines)+"\n")
print("\n".join(lines))
