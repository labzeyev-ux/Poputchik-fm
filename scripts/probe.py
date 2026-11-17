import requests, re, json
UA = {"User-Agent": "PoputchikFM-builder/1.0 (GitHub Actions; video news builder)"}
API = "https://commons.wikimedia.org/w/api.php"
for q in ["Crimean Bridge", "Bundestag", "Bundeskanzleramt", "Patriot missile", "electricity pylon", "Bitcoin", "oil tanker", "Stuttgart", "telephone", "wildlife crossing", "server room", "Hamburg", "Hells Angels", "Euro banknotes", "APEC"]:
    p = {"action":"query","format":"json","generator":"search","gsrsearch":f"{q} filetype:video","gsrnamespace":6,"gsrlimit":8,
         "prop":"videoinfo","viprop":"url|size|mime|extmetadata|derivatives","formatversion":2}
    r = requests.get(API, params=p, headers=UA, timeout=30).json()
    print("==", q, len(r.get("query",{}).get("pages",[])))
    for pg in r.get("query",{}).get("pages",[]):
        vi = (pg.get("videoinfo") or [{}])[0]; em = vi.get("extmetadata",{})
        lic = em.get("LicenseShortName",{}).get("value"); art = re.sub("<[^>]+>","",em.get("Artist",{}).get("value",""))[:40]
        ders = [d.get("type","")+"|"+str(d.get("height","")) for d in vi.get("derivatives",[])][:6]
        print(" ", pg["title"][:70], "|", vi.get("duration"), "|", lic, "|", art, "|", vi.get("width"), "x", vi.get("height"), "|", ders[:4])
print("==== EU AV")
for u in ["https://audiovisual.ec.europa.eu/en/search?keywords=Ukraine&mediatype=VIDEO",
          "https://audiovisual.ec.europa.eu/en/video",
          "https://audiovisual.ec.europa.eu/en/stockshots"]:
    try:
        r = requests.get(u, headers=UA, timeout=30)
        print(u, r.status_code, len(r.text))
        print(sorted(set(re.findall(r'/en/video/I-\d+', r.text)))[:15])
        print(sorted(set(re.findall(r'https?://[^"\']+\.mp4', r.text)))[:10])
        print(sorted(set(re.findall(r'(?:api|json)[^"\' ]{0,80}', r.text)))[:15])
    except Exception as e: print(u, e)
try:
    r = requests.get("https://audiovisual.ec.europa.eu/en/video/I-280000", headers=UA, timeout=30)
    print("item", r.status_code, sorted(set(re.findall(r'https?://[^"\'\s]+\.(?:mp4|m3u8)', r.text)))[:10])
    print(r.text[:1500])
except Exception as e: print(e)
