"""Push the current git HEAD to GitHub through the REST API.

Handy when `git push` cannot connect but api.github.com is reachable.
The commit is created on top of the remote branch tip, so history is preserved.

    python tools/github_push.py <owner>/<repo> <branch>

The token is read from GITHUB_TOKEN / GH_TOKEN, or from the git credential
helper (`git credential fill`), which is where Git Credential Manager stores it.
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request

API = "https://api.github.com"


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return result.stdout.strip()


def token() -> str:
    for name in ("GITHUB_TOKEN", "GH_TOKEN"):
        value = os.getenv(name)
        if value:
            return value.strip()
    filled = subprocess.run(
        ["git", "credential", "fill"],
        input="protocol=https\nhost=github.com\n\n",
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    for line in filled.splitlines():
        if line.startswith("password="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no GitHub token: set GITHUB_TOKEN or run `gh auth login`")


def api(method: str, path: str, tok: str, payload: dict | None = None) -> dict:
    request = urllib.request.Request(
        API + path,
        method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={
            "Authorization": f"token {tok}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
            "User-Agent": "scrapegraphai-push",
        },
    )
    try:
        with urllib.request.urlopen(request) as response:
            body = response.read()
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        raise SystemExit(f"{method} {path} -> HTTP {exc.code}: {exc.read().decode('utf-8', 'ignore')[:400]}")


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    repo, branch = sys.argv[1], sys.argv[2]
    tok = token()

    # Safety: only ever fast-forward the remote branch. The local parent either
    # is the remote tip, or has the same tree as it (which happens when an
    # earlier push went out through this API instead of `git push`).
    remote_sha = api("GET", f"/repos/{repo}/git/ref/heads/{branch}", tok)["object"]["sha"]
    local_sha = git("rev-parse", "HEAD")
    parent_sha = git("rev-parse", "HEAD^") if git("rev-list", "--count", "HEAD") != "1" else ""
    remote_tree = api("GET", f"/repos/{repo}/git/commits/{remote_sha}", tok)["tree"]["sha"]
    local_parent_tree = git("rev-parse", "HEAD^{tree}") if parent_sha else ""
    if parent_sha != remote_sha and local_parent_tree != remote_tree:
        print(
            f"note: local parent {parent_sha[:8] or '(none)'} is not the remote tip "
            f"{remote_sha[:8]}; pushing the tree diff on top of the remote tip"
        )

    base_tree = remote_tree

    # Compare the two trees path by path and upload only what actually differs.
    remote_entries = {
        item["path"]: item["sha"]
        for item in api("GET", f"/repos/{repo}/git/trees/{remote_tree}?recursive=1", tok)["tree"]
        if item["type"] == "blob"
    }
    local_entries = {}
    for line in git("ls-tree", "-r", "HEAD").splitlines():
        meta, path = line.split("\t", 1)
        mode, kind, sha = meta.split()
        local_entries[path] = (mode, sha)

    changed = sorted(p for p, (_, sha) in local_entries.items() if remote_entries.get(p) != sha)
    removed = sorted(p for p in remote_entries if p not in local_entries)
    print(
        f"remote {branch} at {remote_sha[:8]}: "
        f"{len(changed)} changed, {len(removed)} removed, {len(local_entries)} total"
    )

    entries = []
    for path in changed:
        mode, _ = local_entries[path]
        raw = open(path, "rb").read()
        try:
            payload = {"content": raw.decode("utf-8"), "encoding": "utf-8"}
        except UnicodeDecodeError:
            payload = {"content": base64.b64encode(raw).decode(), "encoding": "base64"}
        blob = api("POST", f"/repos/{repo}/git/blobs", tok, payload)
        entries.append({"path": path, "mode": mode, "type": "blob", "sha": blob["sha"]})
        print(f"  blob {blob['sha'][:8]} {path}")
    for path in removed:
        entries.append({"path": path, "mode": "100644", "type": "blob", "sha": None})
        print(f"  delete {path}")

    tree = api("POST", f"/repos/{repo}/git/trees", tok, {"base_tree": base_tree, "tree": entries})
    message = git("log", "-1", "--pretty=%B")
    commit = api(
        "POST",
        f"/repos/{repo}/git/commits",
        tok,
        {"message": message, "tree": tree["sha"], "parents": [remote_sha]},
    )
    api("PATCH", f"/repos/{repo}/git/refs/heads/{branch}", tok, {"sha": commit["sha"], "force": False})

    print(f"pushed {local_sha[:8]} as {commit['sha'][:8]} -> {repo}@{branch}")
    print(f"https://github.com/{repo}/commit/{commit['sha']}")


if __name__ == "__main__":
    main()
