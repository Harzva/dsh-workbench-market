"""Rank discovered Web packages for manual review without treating hints as approvals."""
import argparse
import collections
import json
import re
from pathlib import Path

from discover import ROOT
from review_web_candidates import key, TASK_HINT


PANEL = re.compile(r"主面板|主区域|右侧栏|侧边栏|会话旁|独立面板|right sidebar|main panel|full-screen|dock(?:ed|ing)", re.I)
ACTION = re.compile(r"新建|编辑|保存|导出|审查|筛选|恢复|管理|预览|\b(?:create|edit|save|export|review|filter|restore|manage|preview)\b", re.I)


def read_dossiers(paths):
    dossiers = {}
    for path in paths:
        with path.open(encoding="utf-8") as file:
            for line in file:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    if not line.endswith("\n"):  # A live scan can be appending its final line.
                        break
                    raise
                identity = key(row)
                old = dossiers.get(identity, {})
                quality = row.get("observedAt") or "", bool(row.get("clientEvidence"))
                previous_quality = old.get("observedAt") or "", bool(old.get("clientEvidence"))
                if quality >= previous_quality:
                    dossiers[identity] = row
    return dossiers


def priority(candidate, dossier):
    excerpt_lines = [line for doc in dossier.get("documents", []) for _, line in doc["excerpts"]]
    description = " ".join(str(dossier.get(field) or candidate.get(field) or "") for field in ("name", "description"))
    evidence = dossier.get("clientEvidence") or {}
    return (
        5 * bool(evidence.get("hooks"))
        + 3 * bool(TASK_HINT.search(description))
        + 2 * bool(PANEL.search(description))
        + min(6, sum(bool(PANEL.search(line) and ACTION.search(line)) for line in excerpt_lines))
    )


def build_queue(candidates, published, dossiers):
    entries = {key(row) for row in published if row["host"] in {"web", "deepseek-desktop"}}
    counts = collections.Counter()
    queue = []
    for candidate in candidates:
        identity = key(candidate)
        if identity in entries:
            counts["published"] += 1
            continue
        dossier = dossiers.get(identity, {})
        status = dossier.get("status", "unread")
        if dossier and (candidate.get("observedAt") or "") > (dossier.get("observedAt") or ""):
            status = "dossier_outdated"
        elif status == "review":
            status = "with_client_hint" if (dossier.get("clientEvidence") or {}).get("hooks") else "with_dossier"
        counts[status] += 1
        queue.append({
            "repo": candidate["repo"],
            "packagePath": candidate["packagePath"],
            "package": candidate.get("package"),
            "description": dossier.get("description") or candidate.get("description") or "",
            "priority": priority(candidate, dossier),
            "status": status,
        })
    queue.sort(key=lambda row: (-row["priority"], key(row)))
    return counts, queue


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--discovery", type=Path, default=ROOT / "discovery.json")
    parser.add_argument("--catalog", type=Path, default=ROOT / "dist" / "index.json")
    parser.add_argument("--dossiers", type=Path, nargs="+", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    candidates = json.loads(args.discovery.read_text(encoding="utf-8"))["webCandidates"]
    published = json.loads(args.catalog.read_text(encoding="utf-8"))["entries"]
    counts, queue = build_queue(candidates, published, read_dossiers(args.dossiers))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scratch = args.output.with_suffix(".tmp")
    with scratch.open("w", encoding="utf-8") as output:
        for row in queue:
            output.write(json.dumps(row, ensure_ascii=False) + "\n")
    scratch.replace(args.output)
    print(json.dumps({"candidates": len(candidates), "states": counts, "awaitingReview": len(queue)}))


if __name__ == "__main__":
    main()
