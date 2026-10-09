"""
Web data API: scrape / extract / search / crawl / monitor.

The LLM backend is picked from the environment so the same file runs locally and
on a cloud host:

    LLM_PROVIDER=deepseek  DEEPSEEK_API_KEY=sk-...      (used when the key is set)
    LLM_PROVIDER=openai    OPENAI_API_KEY=sk-...        OPENAI_BASE_URL=...
    LLM_PROVIDER=ollama    OLLAMA_BASE_URL=http://localhost:11434

Pages are fetched with plain HTTP requests, so no browser / Playwright is needed.
"""
from __future__ import annotations

import hashlib
import os
import time
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import asyncio
import html2text
import requests
import uvicorn
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # dotenv is optional
    pass

BASE_DIR = Path(__file__).resolve().parent

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; ScrapeGraphAI-clone/2.0; "
        "+https://github.com/ScrapeGraphAI/Scrapegraph-ai)"
    )
}

# ---- tunables (all overridable from the environment) ----
MAX_CHARS = int(os.getenv("MAX_CHARS", "100000"))
REQUEST_TIMEOUT = int(os.getenv("REQUEST_TIMEOUT", "30"))
PORT = int(os.getenv("PORT", "8000"))
RATE_PER_MINUTE = int(os.getenv("RATE_PER_MINUTE", "20"))
DAILY_QUOTA = int(os.getenv("DAILY_QUOTA", "500"))
LLM_TOKENS = int(os.getenv("LLM_TOKENS", "8192"))
PUBLIC_API_KEY = (os.getenv("PUBLIC_API_KEY") or "").strip()
CORS_ORIGINS = [o.strip() for o in (os.getenv("CORS_ORIGINS") or "*").split(",") if o.strip()]

app = FastAPI(title="ScrapeGraphAI", version="2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

executor = ThreadPoolExecutor(max_workers=int(os.getenv("WORKERS", "4")))

# url -> content hash (in-memory, resets when the process restarts)
monitor_state: dict[str, str] = {}
# client ip -> request timestamps in the last 60s
_hits: dict[str, deque] = defaultdict(deque)
# very rough global daily counter
_quota = {"day": "", "used": 0}


# --------------------------------------------------------------------------- #
# LLM configuration
# --------------------------------------------------------------------------- #
def _provider() -> str:
    """Resolve which LLM provider this process should talk to."""
    explicit = (os.getenv("LLM_PROVIDER") or "").strip().lower()
    if explicit:
        return explicit
    if os.getenv("DEEPSEEK_API_KEY"):
        return "deepseek"
    if os.getenv("OPENAI_API_KEY"):
        return "openai"
    return "ollama"


def llm_config() -> dict:
    """Build the graph config for the active provider."""
    provider = _provider()
    common = {"temperature": 0, "model_tokens": LLM_TOKENS}

    if provider == "deepseek":
        llm = {
            "model": os.getenv("LLM_MODEL", "deepseek/deepseek-chat"),
            "api_key": os.getenv("DEEPSEEK_API_KEY", ""),
            **common,
        }
    elif provider == "openai":
        llm = {
            "model": os.getenv("LLM_MODEL", "openai/gpt-4o-mini"),
            "api_key": os.getenv("OPENAI_API_KEY", ""),
            **common,
        }
        if os.getenv("OPENAI_BASE_URL"):
            llm["base_url"] = os.environ["OPENAI_BASE_URL"]
    else:
        llm = {
            "model": os.getenv("LLM_MODEL", "ollama/llama3.2"),
            "base_url": os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            **common,
        }

    return {"llm": llm, "verbose": False, "headless": True}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def _run(fn):
    """Run a blocking helper in the thread pool instead of the event loop."""
    loop = asyncio.get_running_loop()
    return loop.run_in_executor(executor, fn)


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _guard(request: Request):
    """Return a JSON error response when the caller is out of budget, else None."""
    if PUBLIC_API_KEY:
        sent = request.headers.get("x-api-key") or ""
        auth = request.headers.get("authorization") or ""
        if sent != PUBLIC_API_KEY and auth != f"Bearer {PUBLIC_API_KEY}":
            return JSONResponse(
                {"error": "缺少或错误的 API Key / missing or invalid API key"},
                status_code=401,
            )

    today = time.strftime("%Y-%m-%d")
    if _quota["day"] != today:
        _quota["day"], _quota["used"] = today, 0

    if DAILY_QUOTA and _quota["used"] >= DAILY_QUOTA:
        return JSONResponse(
            {"error": "今日免费额度已用完，请明天再试 / daily quota reached, try again tomorrow"},
            status_code=429,
        )

    if RATE_PER_MINUTE:
        now = time.time()
        bucket = _hits[_client_ip(request)]
        while bucket and now - bucket[0] > 60:
            bucket.popleft()
        if len(bucket) >= RATE_PER_MINUTE:
            return JSONResponse(
                {"error": "请求过于频繁，请稍后再试 / too many requests, slow down"},
                status_code=429,
            )
        bucket.append(now)

    _quota["used"] += 1
    return None


def fetch_html(url: str, timeout: int | None = None) -> str:
    """GET a URL and return its decoded HTML."""
    resp = requests.get(url, headers=HEADERS, timeout=timeout or REQUEST_TIMEOUT)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def to_markdown(url: str, max_chars: int = MAX_CHARS) -> str:
    """Fetch a page and convert it to clean Markdown (requests + html2text)."""
    converter = html2text.HTML2Text()
    converter.ignore_links = False
    converter.ignore_images = True
    converter.body_width = 0
    return converter.handle(fetch_html(url))[:max_chars]


def _bad_request(message: str) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=400)


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
async def home():
    return (BASE_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/index.html", response_class=HTMLResponse)
async def home_alias():
    return (BASE_DIR / "index.html").read_text(encoding="utf-8")


@app.get("/api/health")
async def api_health():
    """Cheap probe used by the UI and by uptime checks."""
    provider = _provider()
    return JSONResponse(
        {
            "status": "ok",
            "provider": provider,
            "model": llm_config()["llm"].get("model"),
            "rate_limit_per_minute": RATE_PER_MINUTE,
            "daily_quota": DAILY_QUOTA,
            "requires_api_key": bool(PUBLIC_API_KEY),
        }
    )


@app.post("/api/scrape")
async def api_scrape(request: Request):
    """URL -> clean Markdown (no AI involved)."""
    blocked = _guard(request)
    if blocked:
        return blocked

    data = await request.json()
    url = (data.get("url") or "").strip()
    if not url:
        return _bad_request("请输入 URL")

    try:
        markdown = await _run(lambda: to_markdown(url))
        return JSONResponse({"url": url, "markdown": markdown})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/extract")
async def api_extract(request: Request):
    """URL + natural-language prompt -> structured JSON."""
    blocked = _guard(request)
    if blocked:
        return blocked

    data = await request.json()
    url = (data.get("url") or "").strip()
    prompt = (data.get("prompt") or "提取这个页面的主要内容").strip()
    if not url:
        return _bad_request("请输入 URL")

    def do():
        # Fetch the page ourselves and hand the raw HTML to the graph, which keeps
        # the request path browser-free.
        from scrapegraphai.graphs import SmartScraperGraph

        html = fetch_html(url)
        graph = SmartScraperGraph(prompt=prompt, source=html, config=llm_config())
        return graph.run()

    try:
        result = await _run(do)
        return JSONResponse({"url": url, "prompt": prompt, "data": result})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/search")
async def api_search(request: Request):
    """Search the web (DuckDuckGo) and return the result list."""
    blocked = _guard(request)
    if blocked:
        return blocked

    data = await request.json()
    query = (data.get("query") or "").strip()
    num = min(int(data.get("numResults") or 5), 10)
    if not query:
        return _bad_request("请输入搜索关键词")

    def do():
        from ddgs import DDGS

        with DDGS() as ddgs:
            rows = list(ddgs.text(query, max_results=num))
        return [
            {"title": r.get("title", ""), "href": r.get("href", ""), "body": r.get("body", "")}
            for r in rows
        ]

    try:
        results = await _run(do)
        return JSONResponse({"query": query, "count": len(results), "results": results})
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/crawl")
async def api_crawl(request: Request):
    """Crawl a site: home page plus same-origin links, each converted to Markdown."""
    blocked = _guard(request)
    if blocked:
        return blocked

    data = await request.json()
    url = (data.get("url") or "").strip()
    max_pages = min(int(data.get("maxPages") or 10), 20)
    if not url:
        return _bad_request("请输入 URL")

    def do():
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin, urlparse

        soup = BeautifulSoup(fetch_html(url), "html.parser")
        base = urlparse(url)
        links, seen = [], set()
        for anchor in soup.find_all("a", href=True):
            href = urljoin(url, anchor["href"].strip())
            parsed = urlparse(href)
            if parsed.scheme in ("http", "https") and parsed.netloc == base.netloc and href not in seen:
                seen.add(href)
                links.append(href)
            if len(links) >= max_pages - 1:
                break

        targets = [url] + links[: max_pages - 1]
        pages = []
        for index, page_url in enumerate(targets, 1):
            try:
                pages.append({"index": index, "url": page_url, "markdown": to_markdown(page_url, 3000)})
            except Exception as exc:
                pages.append({"index": index, "url": page_url, "error": str(exc)})
        return {"root": url, "total": len(pages), "pages": pages}

    try:
        return JSONResponse(await _run(do))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.post("/api/monitor")
async def api_monitor(request: Request):
    """Fingerprint a page and report whether it changed since the last check."""
    blocked = _guard(request)
    if blocked:
        return blocked

    data = await request.json()
    url = (data.get("url") or "").strip()
    webhook = (data.get("webhook") or "").strip()
    if not url:
        return _bad_request("请输入 URL")

    def do():
        body = fetch_html(url)
        digest = hashlib.sha256(body.encode("utf-8", "ignore")).hexdigest()[:16]
        previous = monitor_state.get(url)
        changed = previous is not None and previous != digest
        monitor_state[url] = digest
        if changed and webhook:
            try:
                requests.post(webhook, json={"url": url, "changed": True}, timeout=10)
            except Exception:
                pass
        return {
            "url": url,
            "changed": changed,
            "hash": digest,
            "first_check": previous is None,
            "note": "第二次检查同一个 URL 才会对比变化；配置 webhook 可在变化时收到通知",
        }

    try:
        return JSONResponse(await _run(do))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


# Serve the marketing images referenced by index.html. Mounted last so it never
# shadows the API routes, and scoped to one folder so nothing else is exposed.
_images = BASE_DIR / "images"
if _images.is_dir():
    app.mount("/images", StaticFiles(directory=_images), name="images")


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT)
