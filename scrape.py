"""
ScrapeGraphAI 命令行工具 - 完整功能
本地 AI: Ollama + llama3.2 (免费, 不联网)

用法:
  python scrape.py scrape  <网址>                        # URL -> 干净 Markdown
  python scrape.py extract <网址> "<要提取什么>"          # URL + 描述 -> 结构化 JSON
  python scrape.py search  "<搜索关键词>"                 # 搜索 -> AI 汇总答案
  python scrape.py crawl   <网址> [最大页数]              # 整站爬取 (默认 10 页)
  python scrape.py monitor <网址> [webhook地址]           # 监控页面变化

例子:
  python scrape.py scrape https://news.ycombinator.com
  python scrape.py extract https://news.ycombinator.com "提取前5条新闻标题和链接"
  python scrape.py search "sustainable packaging trends 2026"
  python scrape.py crawl https://example.com 5
"""
import json
import sys

import requests
import html2text

from scrapegraphai.graphs import SmartScraperGraph

LLM_CONFIG = {
    "llm": {
        "model": "ollama/llama3.2",
        "temperature": 0,
        "base_url": "http://localhost:11434",
        "model_tokens": 8192,
    },
    "verbose": False,
    "headless": True,
}

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ScrapeGraphAI-clone/2.0)"}


def to_markdown(url: str, max_chars: int = 100000) -> str:
    """抓取网页并转成干净 Markdown (requests + html2text, 不依赖浏览器)"""
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    if not resp.encoding or resp.encoding.lower() == "iso-8859-1":
        resp.encoding = "utf-8"
    h = html2text.HTML2Text()
    h.ignore_links = False
    h.body_width = 0
    h.ignore_images = True
    md = h.handle(resp.text)
    return md[:max_chars]


def cmd_scrape(url: str):
    print(f"正在把 {url} 转成 Markdown ...")
    print("\n===== Markdown =====")
    print(to_markdown(url))


def cmd_extract(url: str, prompt: str):
    print(f"AI 正在分析 {url} ...")
    graph = SmartScraperGraph(prompt=prompt, source=url, config=LLM_CONFIG)
    result = graph.run()
    print("\n===== 提取结果 =====")
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_search(query: str, num: int = 5):
    from ddgs import DDGS

    print(f"正在搜索: {query} ...")
    with DDGS() as ddgs:
        results = list(ddgs.text(query, max_results=num))
    print("\n===== 搜索结果 =====")
    for i, r in enumerate(results, 1):
        print(f"[{i}] {r.get('title')}")
        print(f"    {r.get('href')}")
        print(f"    {r.get('body', '')[:120]}")
    print(f"\n共 {len(results)} 条结果")


def cmd_crawl(url: str, max_pages: int = 10):
    import requests
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin, urlparse

    print(f"正在爬取 {url} (最多 {max_pages} 页) ...")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ScrapeGraphAI-clone/2.0)"}
    html = requests.get(url, headers=headers, timeout=30).text
    soup = BeautifulSoup(html, "html.parser")
    base = urlparse(url)
    links, seen = [], set()
    for a in soup.find_all("a", href=True):
        href = urljoin(url, a["href"].strip())
        p = urlparse(href)
        if p.scheme in ("http", "https") and p.netloc == base.netloc and href not in seen:
            seen.add(href)
            links.append(href)
        if len(links) >= max_pages - 1:
            break

    targets = [url] + links[: max_pages - 1]
    for i, page_url in enumerate(targets, 1):
        print(f"\n--- [{i}/{len(targets)}] {page_url} ---")
        try:
            print(to_markdown(page_url, 2000))
        except Exception as e:
            print(f"失败: {e}")


def cmd_monitor(url: str, webhook: str = ""):
    import hashlib
    import requests

    print(f"正在检查 {url} ...")
    headers = {"User-Agent": "Mozilla/5.0 (compatible; ScrapeGraphAI-clone/2.0)"}
    content = requests.get(url, headers=headers, timeout=30).text
    h = hashlib.sha256(content.encode("utf-8", "ignore")).hexdigest()[:16]
    print(f"内容指纹: {h}")
    print("提示: 再运行一次同一条命令即可对比内容是否有变化")
    if webhook:
        requests.post(webhook, json={"url": url, "hash": h}, timeout=10)
        print(f"已通知 webhook: {webhook}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    mode = sys.argv[1].lower()
    if mode == "scrape" and len(sys.argv) >= 3:
        cmd_scrape(sys.argv[2])
    elif mode == "extract" and len(sys.argv) >= 3:
        prompt = sys.argv[3] if len(sys.argv) >= 4 else "提取这个页面的主要内容"
        cmd_extract(sys.argv[2], prompt)
    elif mode == "search" and len(sys.argv) >= 3:
        num = int(sys.argv[3]) if len(sys.argv) >= 4 else 5
        cmd_search(sys.argv[2], num)
    elif mode == "crawl" and len(sys.argv) >= 3:
        num = int(sys.argv[3]) if len(sys.argv) >= 4 else 10
        cmd_crawl(sys.argv[2], num)
    elif mode == "monitor" and len(sys.argv) >= 3:
        webhook = sys.argv[3] if len(sys.argv) >= 4 else ""
        cmd_monitor(sys.argv[2], webhook)
    else:
        print(__doc__)


if __name__ == "__main__":
    main()
