import requests, time
U = "https://upload.wikimedia.org/wikipedia/commons/transcoded/f/fb/Drone_video_of_Kolu_wildlife_overpass_in_Estonia.webm/Drone_video_of_Kolu_wildlife_overpass_in_Estonia.webm.720p.vp9.webm"
O = "https://upload.wikimedia.org/wikipedia/commons/f/fb/Drone_video_of_Kolu_wildlife_overpass_in_Estonia.webm"
for name, ua in [("custom", "PoputchikFM-builder/2.0 (GitHub Actions; news video builder)"),
                 ("bot-style", "NewsVideoBuilder/2.0 (https://www.mediawiki.org/wiki/API:Etiquette) python-requests/2"),
                 ("default", None)]:
    for url in (U, O):
        h = {"User-Agent": ua} if ua else {}
        try:
            r = requests.get(url, headers=h, stream=True, timeout=30)
            n = 0
            if r.ok:
                for c in r.iter_content(1 << 16):
                    n += len(c)
                    if n > 3_000_000: break
            print(name, url[-30:], r.status_code, n, {k: v for k, v in r.headers.items() if k.lower() in ("retry-after", "x-cache", "server", "x-client-ip", "content-length")})
            if not r.ok: print("   body:", r.text[:300].replace("\n", " "))
        except Exception as e:
            print(name, e)
        time.sleep(3)
