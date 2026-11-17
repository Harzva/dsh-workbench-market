"""Collect workflow and optional client source hints for manual GitHub workbench review."""
import argparse
import concurrent.futures
import json
import re
import urllib.error
from pathlib import Path

from discover import REPO, ROOT, clean_path, client_entry, fetch, raw_url, web_client, web_signal

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
CLIENT_HOOK = re.compile(
    r"""\b(?:sidebar\.panellist|sidebar\.footer\.action|sidebar\.right\.pane\.tab|"""
    r"""sidebar\.right\.tab\.document|shell\.overlay|conversation\.view|conversation\.input\.dock|settings\.plugins\.tab)\b|"""
    r"""\b(?:sidebarRightTabs|desktopWorkbenches|documentPreviews)\s*(?:\?\.|\.)\s*register\b|"""
    r"""\bbetterSidebar\s*(?:\?\.|\.)\s*registerTab\b|"""
    r"""(?:\b(?:register|inject)\s*\(\s*|\bname\s*:\s*)['"]main['"]"""
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
        if not isinstance(manifest, dict) or not web_client(manifest):
            return {**record, "status": "manifest_changed"}
        needs_assembly = not web_signal(manifest)
        if needs_assembly and not row.get("requiresAssembly"):
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
            **({"requiresAssembly": True} if needs_assembly else {}),
        }
    except (OSError, UnicodeError, ValueError) as error:
        return {**record, "status": "fetch_error", "error": str(error)}


def collect_client(record):
    if record["status"] != "review":
        return record
    repo, ref = record["repo"], record["ref"]
    parent = record["packagePath"].rpartition("/")[0]
    fallback = (
        "src/client.ts", "src/client.tsx", "src/client.js", "src/client/index.ts",
        "src/client/index.tsx", "src/client/index.js", "src/client-entry.js",
        "client.js", "client.ts",
    )
    candidate_paths = dict.fromkeys([
        record["client"], *(f"{parent}/{path}" if parent else path for path in fallback),
    ])
    inspected = []
    errors = []
    for path in candidate_paths:
        try:
            source = read_file(repo, ref, path, limit=3_000_000)
        except (OSError, UnicodeError, ValueError) as error:
            errors.append({"path": path, "error": str(error)})
            continue
        if source is None:
            continue
        inspected.append(path)
        hints = {}
        for number, line in enumerate(source.splitlines(), 1):
            for match in CLIENT_HOOK.finditer(line):
                hints.setdefault(match.group(), number)
        if hints:
            return {**record, "clientEvidence": {"path": path, "hooks": hints, "errors": errors}}
    return {**record, "clientEvidence": {"inspected": inspected, "errors": errors}}


def review(row, previous, include_client):
    record = previous or collect(row)
    return collect_client(record) if include_client else record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", nargs="*", type=Path, default=[ROOT / "discovery.json"])
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=250, help="Maximum new candidate dossiers per run.")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--retry-errors", action="store_true")
    parser.add_argument("--client-evidence", action="store_true",
                        help="Check client code for known host hooks, reusing saved README excerpts.")
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
        snapshot = json.loads(report.read_text())
        for row in snapshot.get("webCandidates", []):
            if not row.get("observedAt") and snapshot.get("checkedAt"):
                row = {**row, "observedAt": snapshot["checkedAt"]}
            ident = key(row)
            old = rows.get(ident, {})
            if not old or (row.get("observedAt") or "") >= (old.get("observedAt") or ""):
                rows[ident] = row
    pending = []
    for ident, row in rows.items():
        if ident in reviewed:
            continue
        old = processed.get(ident)
        if not old or (row.get("observedAt") or "") > (old.get("observedAt") or ""):
            pending.append((row, None))
        elif args.client_evidence and old["status"] == "review":
            evidence = old.get("clientEvidence")
            if evidence is None or (args.retry_errors and evidence.get("errors")):
                pending.append((row, old))
    pending.sort(key=lambda entry: (not priority(entry[0]), key(entry[0])))
    batch = pending[:args.limit]
    print(f"Reading {len(batch)}/{len(pending)} unread Web candidates", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool, args.output.open("a") as output:
        futures = [pool.submit(review, row, old, args.client_evidence) for row, old in batch]
        for count, future in enumerate(concurrent.futures.as_completed(futures), 1):
            row = future.result()
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
            output.flush()
            if count % 50 == 0 or count == len(batch):
                print(f"{count}/{len(batch)} dossiers written", flush=True)


if __name__ == "__main__":
    main()
