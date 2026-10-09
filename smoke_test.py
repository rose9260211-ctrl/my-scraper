"""Quick smoke test against a running server (python smoke_test.py [base_url])."""
import json
import sys
import time

import requests

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000").rstrip("/")


def call(name: str, path: str, payload: dict | None = None, timeout: int = 120):
    started = time.time()
    try:
        if payload is None:
            resp = requests.get(BASE + path, timeout=timeout)
        else:
            resp = requests.post(BASE + path, json=payload, timeout=timeout)
        took = time.time() - started
        try:
            body = resp.json()
        except ValueError:
            body = resp.text[:200]
        preview = json.dumps(body, ensure_ascii=False) if not isinstance(body, str) else body
        print(f"[{resp.status_code}] {name:<10} {took:6.2f}s  {preview[:220]}")
        return body
    except Exception as exc:
        print(f"[ERR] {name:<10} {type(exc).__name__}: {exc}")
        return None


if __name__ == "__main__":
    print(f"--- smoke test against {BASE} ---")
    call("health", "/api/health")
    call("page", "/index.html")
    call("scrape", "/api/scrape", {"url": "https://example.com"})
    call("search", "/api/search", {"query": "python web scraping", "numResults": 2})
    call("monitor", "/api/monitor", {"url": "https://example.com"})
    call("monitor2", "/api/monitor", {"url": "https://example.com"})
    call("crawl", "/api/crawl", {"url": "https://example.com", "maxPages": 2})
    call("extract", "/api/extract", {"url": "https://example.com", "prompt": "Return the page title and the main heading as JSON"})
