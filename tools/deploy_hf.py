"""Deploy this folder to a Hugging Face Docker Space.

    python tools/deploy_hf.py <space-name> [--token hf_xxx]

Token lookup order: --token, HF_TOKEN, HUGGINGFACE_TOKEN,
~/.cache/huggingface/token.

The Space is created if missing, every deploy file is uploaded in one commit,
and DEEPSEEK_API_KEY is pushed as a Space secret when it is available locally.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
HUB = "https://huggingface.co"

# Everything the Space needs to build and serve the site.
DEPLOY_FILES = [
    "README.md",
    "Dockerfile",
    ".dockerignore",
    "requirements.txt",
    "server.py",
    "index.html",
]
DEPLOY_GLOBS = ["images/*"]


def find_token(argv: list[str]) -> str:
    if "--token" in argv:
        return argv[argv.index("--token") + 1].strip()
    for name in ("HF_TOKEN", "HUGGINGFACE_TOKEN"):
        if os.getenv(name):
            return os.environ[name].strip()
    cached = Path.home() / ".cache" / "huggingface" / "token"
    if cached.is_file():
        return cached.read_text(encoding="utf-8").strip()
    raise SystemExit("no Hugging Face token: pass --token hf_xxx or set HF_TOKEN")


def headers(token: str) -> dict:
    return {"Authorization": f"Bearer {token}", "User-Agent": "scrapegraphai-deploy"}


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        raise SystemExit(__doc__)
    space = args[0]
    token = find_token(sys.argv)
    auth = headers(token)

    who = requests.get(f"{HUB}/api/whoami-v2", headers=auth, timeout=30)
    who.raise_for_status()
    user = who.json()["name"]
    repo_id = f"{user}/{space}"
    print(f"authenticated as {user} -> {repo_id}")

    created = requests.post(
        f"{HUB}/api/repos/create",
        headers=auth,
        json={"type": "space", "name": space, "sdk": "docker", "private": False},
        timeout=60,
    )
    if created.status_code in (200, 201):
        print("space created")
    elif created.status_code == 409:
        print("space already exists, updating it")
    else:
        raise SystemExit(f"create failed: {created.status_code} {created.text[:300]}")

    paths = [ROOT / name for name in DEPLOY_FILES]
    for pattern in DEPLOY_GLOBS:
        paths.extend(sorted(ROOT.glob(pattern)))

    lines = [json.dumps({"key": "header", "value": {"summary": "Deploy site and API backend"}})]
    for path in paths:
        if not path.is_file():
            print(f"  skip (missing) {path.name}")
            continue
        rel = path.relative_to(ROOT).as_posix()
        content = base64.b64encode(path.read_bytes()).decode()
        lines.append(
            json.dumps(
                {"key": "file", "value": {"path": rel, "content": content, "encoding": "base64"}}
            )
        )
        print(f"  upload {rel} ({path.stat().st_size} bytes)")

    commit = requests.post(
        f"{HUB}/api/spaces/{repo_id}/commit/main",
        headers={**auth, "Content-Type": "application/x-ndjson"},
        data="\n".join(lines).encode(),
        timeout=300,
    )
    if commit.status_code not in (200, 201):
        raise SystemExit(f"commit failed: {commit.status_code} {commit.text[:300]}")
    print(f"commit ok: {commit.json().get('commitOid', '')[:8]}")

    secret = os.getenv("DEEPSEEK_API_KEY")
    if not secret and (ROOT / ".env").is_file():
        for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
            if line.startswith("DEEPSEEK_API_KEY="):
                secret = line.split("=", 1)[1].strip()
    if secret:
        pushed = requests.post(
            f"{HUB}/api/spaces/{repo_id}/secrets",
            headers=auth,
            json={"key": "DEEPSEEK_API_KEY", "value": secret, "description": "LLM key for /api/extract"},
            timeout=60,
        )
        print(f"set DEEPSEEK_API_KEY secret: HTTP {pushed.status_code}")
    else:
        print("no DEEPSEEK_API_KEY found locally - set it in the Space settings")

    print(f"\nspace:  {HUB}/spaces/{repo_id}")
    print(f"app:    https://{user.lower()}-{space.lower()}.hf.space")
    print(f"logs:   {HUB}/spaces/{repo_id}/logs")


if __name__ == "__main__":
    main()
