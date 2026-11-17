"""Collect README excerpts and client entry points for manual GitHub workbench review."""
import argparse
import concurrent.futures
import json
import re
import urllib.error
from pathlib import Path

from discover import REPO, ROOT, clean_path, client_entry, fetch, raw_url, web_signal

TASK_HINT = re.compile(
    r"工作[台臺]|看板|画布|编辑器|编辑台|仪表[盘盤]|管理台|"
    r"workbench|worktable|studio|dashboard|workspace|canvas|kanban|editor|taskboard|planner",
    re.I,
)
HOST_HINT = re.compile(
    r"DeepSeek Harness|DSH Web|主界面|主面板|侧[栏欄]|侧边[栏欄]|面板|"
    r"sidebar|workbench|main panel|canvas|workspace|工作[台臺]|工作区",
    re.I,
)


def key(row):
    return row["repo"].lower(), row.get("packagePath", "package.json")


def priority(row):
    text = " ".join(str(row.get(field) or "") for field in ("repo", "package", "description"))
    return bool(TASK_HINT.search(text))


def read_file(repo, ref, path, limit=500_000):
    try:
        return fetch(raw_url(repo, ref, path), limit=limit).decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise


def collect(row):
    repo, path = row["repo"], row["packagePath"]
    if not REPO.fullmatch(repo) or clean_path(path) != path:
        raise ValueError("Invalid repository or package path")
    ref = row.get("ref") or "HEAD"
    record = {"repo": repo, "packagePath": path, "ref": ref, "observedAt": row.get("observedAt")}
    try:
        raw = read_file(repo, ref, path)
        if not raw:
            return {**record, "status": "manifest_missing"}
        manifest = json.loads(raw)
        if not isinstance(manifest, dict) or not web_signal(manifest):
            return {**record, "status": "manifest_changed"}
        directory = path.rpartition("/")[0]
        prefix = directory + "/" if directory else ""
        doc_names = ("README.md", "README.zh.md", "README_zh.md", "README.en.md")
        sources = []
        errors = []
        for doc in dict.fromkeys([*(prefix + name for name in doc_names), *doc_names]):
            try:
                body = read_file(repo, ref, doc)
            except (OSError, UnicodeError, ValueError) as error:
                errors.append({"path": doc, "error": str(error)})
                continue
            if body:
                hints = [(number, line.strip()[:240]) for number, line in enumerate(body.splitlines(), 1)
                         if HOST_HINT.search(line) and not line.strip().startswith(("<", "[![", "![", chr(96) * 3))]
                sources.append({"path": doc, "excerpts": hints[:25]})
                if hints or len(sources) == 2:
                    break
        return {
            **record, "status": "review",
            "name": manifest.get("name"), "version": manifest.get("version"),
            "description": manifest.get("description", ""), "client": prefix + client_entry(manifest),
            "documents": sources, "errors": errors,
        }
    except (OSError, UnicodeError, ValueError) as error:
        return {**record, "status": "fetch_error", "error": str(error)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="*", type=Path, default=[ROOT / "discovery.json"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=250, help="Maximum new candidate dossiers per run.")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--retry-errors", action="store_true")
    args = parser.parse_args()
    if args.limit < 1 or not 1 <= args.workers <= 20:
        parser.error("positive limit and 1–20 workers required")

    published = json.loads((ROOT / "dist" / "index.json").read_text())["entries"]
    reviewed = {key(row) for row in published if row["host"] in {"web", "deepseek-desktop"}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    processed = {}
    if args.output.exists():
        for line in args.output.read_text().splitlines():
            row = json.loads(line)
            if row["status"] == "fetch_error" and args.retry_errors:
                processed.pop(key(row), None)
            else:
                processed[key(row)] = row

    rows = {}
    for report in args.reports:
        for row in json.loads(report.read_text()).get("webCandidates", []):
            ident = key(row)
            old = rows.get(ident, {})
            if not old or (row.get("observedAt") or "") >= (old.get("observedAt") or ""):
                rows[ident] = row
    pending = [row for ident, row in rows.items()
               if ident not in reviewed and (
                   ident not in processed or
                   (row.get("observedAt") or "") > (processed[ident].get("observedAt") or "")
               )]
    pending.sort(key=lambda row: (not priority(row), key(row)))
    batch = pending[:args.limit]
    print(f"Reading {len(batch)}/{len(pending)} unread Web candidates", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool, args.output.open("a") as output:
        futures = [pool.submit(collect, row) for row in batch]
        for count, future in enumerate(concurrent.futures.as_completed(futures), 1):
            row = future.result()
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
            output.flush()
            if count % 50 == 0 or count == len(batch):
                print(f"{count}/{len(batch)} dossiers written", flush=True)


if __name__ == "__main__":
    main()
