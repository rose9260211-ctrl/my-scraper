import json, urllib.request, urllib.error, time

def post(path, payload, timeout=240):
    req = urllib.request.Request(
        "http://127.0.0.1:8000" + path,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8", "ignore")
        return r.status, body, round(time.time() - t0, 1)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore"), round(time.time() - t0, 1)

lines = []

# 1) SCRAPE - no AI
try:
    s, b, dt = post("/api/scrape", {"url": "https://example.com"})
    d = json.loads(b)
    lines.append(f"[SCRAPE] status={s} time={dt}s md_len={len(d.get('markdown',''))} ok={('markdown' in d)}")
except Exception as e:
    lines.append(f"[SCRAPE] EXC {e}")

# 2) MONITOR - no AI (2 checks)
for i in (1, 2):
    try:
        s, b, dt = post("/api/monitor", {"url": "https://example.com"})
        d = json.loads(b)
        lines.append(f"[MONITOR{i}] status={s} time={dt}s first={d.get('first_check')} changed={d.get('changed')}")
    except Exception as e:
        lines.append(f"[MONITOR{i}] EXC {e}")

# 3) EXTRACT - AI (llama3.2)
try:
    s, b, dt = post("/api/extract", {"url": "https://example.com", "prompt": "Extract the title and main heading"})
    d = json.loads(b)
    lines.append(f"[EXTRACT] status={s} time={dt}s has_data={'data' in d} data={json.dumps(d.get('data',''), ensure_ascii=False)[:120]}")
except Exception as e:
    lines.append(f"[EXTRACT] EXC {e}")

# 4) SEARCH - AI + duckduckgo
try:
    s, b, dt = post("/api/search", {"query": "sustainable packaging trends 2026", "numResults": 3})
    d = json.loads(b)
    lines.append(f"[SEARCH] status={s} time={dt}s has_data={'data' in d} urls={len(d.get('urls', []))} preview={json.dumps(d.get('data',''), ensure_ascii=False)[:100]}")
except Exception as e:
    lines.append(f"[SEARCH] EXC {e}")

# 5) CRAWL - multi page
try:
    s, b, dt = post("/api/crawl", {"url": "https://example.com", "maxPages": 3})
    d = json.loads(b)
    lines.append(f"[CRAWL] status={s} time={dt}s total={d.get('total')} pages_ok={sum(1 for p in d.get('pages',[]) if 'markdown' in p)}")
except Exception as e:
    lines.append(f"[CRAWL] EXC {e}")

open(r"D:\projects\api_test.txt", "w", encoding="utf-8").write("\n".join(lines))
print("phase1-5 done")
