import requests, re, time, html
UA = {"User-Agent": "NewsVideoBuilder/2.1 (https://www.mediawiki.org/wiki/API:Etiquette) python-requests/2"}
API = "https://commons.wikimedia.org/w/api.php"
def q(s):
    p = {"action":"query","format":"json","formatversion":2,"generator":"search","gsrsearch":f"{s} filetype:video","gsrnamespace":6,"gsrlimit":12,
         "prop":"videoinfo","viprop":"size|extmetadata"}
    for a in range(5):
        r = requests.get(API, params=p, headers=UA, timeout=30)
        if r.ok and r.text.startswith("{"): return r.json()
        time.sleep(5*(a+1))
    return {}
Q = ["Rentner", "senior citizens walking", "elderly people park", "Seniorinnen", "Containerterminal Hamburg", "Burchardkai", "Port of Hamburg", "container ship",
     "Xi Jinping Putin", "Polizei Streifenwagen", "police car Germany", "Blaulicht", "Polizei Nordrhein-Westfalen",
     "laptop typing", "typing keyboard", "smartphone hand", "using smartphone", "online banking", "email",
     "Aston Martin DB5", "James Bond", "Kino Premiere", "red carpet",
     "Europäische Zentralbank", "European Central Bank", "Frankfurt Skyline", "euro coins", "Geldscheine",
     "Akten Stapel", "paperwork", "documents desk", "writing with pen", "Steuererklärung",
     "Rechenzentrum", "server rack", "data center", "Serverraum", "servers",
     "Berlin drone", "Reichstagsgebäude", "Brandenburger Tor Nacht", "Spree Berlin", "Berlin Fernsehturm",
     "Elbphilharmonie", "Düsseldorf Altstadt", "party friends table", "coyote"]
for s in Q:
    r = q(s); time.sleep(1.3)
    pages = sorted(r.get("query",{}).get("pages",[]), key=lambda p: p.get("index",99))
    print("==", s, len(pages))
    for pg in pages:
        vi = (pg.get("videoinfo") or [{}])[0]; em = vi.get("extmetadata",{})
        lic = em.get("LicenseShortName",{}).get("value","")
        w, h, d = vi.get("width") or 0, vi.get("height") or 0, round(vi.get("duration") or 0)
        if w < h*1.2 or h < 480 or d < 6: continue
        if re.search(r"\b(NC|ND)\b", lic): continue
        desc = html.unescape(re.sub(r"<[^>]+>|\s+"," ",em.get("ImageDescription",{}).get("value","")))[:90]
        print(f"  {pg['title'][5:]} | {d}s | {w}x{h} | {lic} | {desc}")
