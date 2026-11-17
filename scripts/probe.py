import requests, re, json, time
UA = {"User-Agent": "PoputchikFM-builder/1.0 (GitHub Actions; video news builder)"}
print("==== EU AV")
for u in ["https://audiovisual.ec.europa.eu/en/search?keywords=Ukraine",
          "https://audiovisual.ec.europa.eu/en/stockshots",
          "https://audiovisual.ec.europa.eu/en/video/I-280000",
          "https://audiovisual.ec.europa.eu/en/terms-and-conditions"]:
    try:
        r = requests.get(u, headers=UA, timeout=30)
        t = r.text
        print("##", u, r.status_code, len(t))
        print(sorted(set(re.findall(r'/en/video/I-\d+', t)))[:15])
        print(sorted(set(re.findall(r'https?://[^"\'\s<>]+\.(?:mp4|m3u8|webm)', t)))[:10])
        print(sorted(set(re.findall(r'["\'](/[^"\'\s]*(?:api|download|media)[^"\'\s]*)', t)))[:20])
        txt = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', re.sub(r'(?s)<script.*?</script>|<style.*?</style>', '', t)))
        i = txt.find('commercial'); print("TXT:", txt[max(0,i-600):i+900] if i>=0 else txt[:1200])
    except Exception as e: print(u, e)
API = "https://commons.wikimedia.org/w/api.php"
def q(s, sort=None):
    p = {"action":"query","format":"json","generator":"search","gsrsearch":f"{s} filetype:video","gsrnamespace":6,"gsrlimit":10,
         "prop":"videoinfo","viprop":"url|size|extmetadata","formatversion":2}
    if sort: p["gsrsort"] = sort
    for a in range(5):
        r = requests.get(API, params=p, headers=UA, timeout=30)
        if r.ok and r.text.startswith("{"): return r.json()
        print("  retry", r.status_code); time.sleep(5*(a+1))
    return {}
for s in ["Crimean Bridge", "Zelensky", "Pattinson", "Friedrich Merz", "Boris Pistorius", "Bundeskanzleramt Berlin", "Reichstag", "European Commission", "Berlaymont",
          "Hells Angels", "Mönchengladbach", "Polizei", "Hamburg Hafen", "Düsseldorf", "Microsoft", "data center", "wildlife overpass", "Xi Jinping Putin", "APEC", "Euro coins", "oil pump", "Commerzbank", "smartphone", "Rentner", "Dnipro Kyiv bridge"]:
    r = q(s, "create_timestamp_desc"); time.sleep(1.5)
    pages = r.get("query",{}).get("pages",[])
    print("==", s, len(pages))
    for pg in pages:
        vi = (pg.get("videoinfo") or [{}])[0]; em = vi.get("extmetadata",{})
        lic = em.get("LicenseShortName",{}).get("value"); art = re.sub(r"<[^>]+>|\s+"," ",em.get("Artist",{}).get("value",""))[:35]
        d = em.get("DateTimeOriginal",{}).get("value","")[:12]
        print("  ", pg["title"][5:75], "|", round(vi.get("duration") or 0), "s |", lic, "|", art, "|", vi.get("width"), "x", vi.get("height"), "|", re.sub(r"<[^>]+>","",d))
