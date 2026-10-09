---
title: ScrapeGraphAI Web Data API
emoji: 🕷️
colorFrom: purple
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
---

# ScrapeGraphAI — web data API

A landing page plus a small FastAPI service that turns webpages into clean
Markdown or structured JSON. Pages are fetched with plain HTTP requests, so no
browser or Playwright is required.

| Endpoint | Input | Output |
| --- | --- | --- |
| `POST /api/scrape` | `{"url": "..."}` | clean Markdown |
| `POST /api/extract` | `{"url": "...", "prompt": "..."}` | structured JSON via an LLM |
| `POST /api/search` | `{"query": "...", "numResults": 5}` | search result list |
| `POST /api/crawl` | `{"url": "...", "maxPages": 10}` | Markdown per page |
| `POST /api/monitor` | `{"url": "...", "webhook": "..."}` | change detection + webhook |
| `GET /api/health` | — | provider, model and rate-limit info |

## Run locally

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements.txt   # Windows
cp .env.example .env                            # then fill in your key
.venv/Scripts/python server.py
```

Open <http://127.0.0.1:8000>.

## Run with Docker

```bash
docker build -t scrapegraphai-web .
docker run --rm -p 8000:7860 --env-file .env scrapegraphai-web
```

## Configuration

Everything is driven by environment variables (see `.env.example`).

| Variable | Default | Purpose |
| --- | --- | --- |
| `LLM_PROVIDER` | auto | `deepseek`, `openai` or `ollama` |
| `DEEPSEEK_API_KEY` | — | used when the provider is `deepseek` |
| `OPENAI_API_KEY` / `OPENAI_BASE_URL` | — | used when the provider is `openai` |
| `OLLAMA_BASE_URL` | `http://localhost:11434` | used when the provider is `ollama` |
| `LLM_MODEL` | provider default | e.g. `deepseek/deepseek-chat` |
| `PORT` | `8000` (`7860` in Docker) | HTTP port |
| `RATE_PER_MINUTE` | `20` | per-IP request budget |
| `DAILY_QUOTA` | `500` | global daily request budget |
| `CORS_ORIGINS` | `*` | comma-separated allowed origins |
| `PUBLIC_API_KEY` | unset | when set, `/api/*` requires the `X-API-Key` header |

The provider is auto-detected when `LLM_PROVIDER` is unset: DeepSeek if
`DEEPSEEK_API_KEY` exists, then OpenAI, then local Ollama.

## Deploy to Hugging Face Spaces

The repository ships a `Dockerfile` and the Space front matter above, so it can
be pushed straight to a Docker Space:

```bash
pip install huggingface_hub
huggingface-cli login
huggingface-cli repo create my-scraper --type space --space_sdk docker
git remote add space https://huggingface.co/spaces/<user>/my-scraper
git push space main
```

Then add `DEEPSEEK_API_KEY` under *Settings → Variables and secrets* and the API
goes live at `https://<user>-my-scraper.hf.space`.

## Notes

- The `scrape` / `crawl` / `monitor` paths never call an LLM — only `extract` and
  `search`-driven summarisation do.
- Change detection keeps hashes in memory, so restarts reset the baseline.
- Public deployments should set `RATE_PER_MINUTE`, `DAILY_QUOTA` and, if the
  page is hosted separately, `PUBLIC_API_KEY` — otherwise anyone can spend your
  LLM credits.

## Tools

| Script | What it does |
| --- | --- |
| `tools/github_push.py <owner>/<repo> <branch>` | push HEAD through the GitHub REST API (useful when `git push` cannot reach github.com) |
| `tools/deploy_hf.py <space-name>` | create/update a Hugging Face Docker Space and set the `DEEPSEEK_API_KEY` secret |
| `tools/screenshot.py [url] [out.png] [--full] [--width 390]` | render a page with Playwright, report JS errors, save a screenshot |
| `smoke_test.py [base_url]` | hit every API endpoint against a running server |
