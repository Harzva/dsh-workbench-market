"""Combine discovery passes without adding overlapping coverage counts."""
import argparse
import json
from collections import Counter
from pathlib import Path

REPORT_FIELDS = ("checkedAt", "repositoriesInspected", "manifestPathsInspected", "indexes", "searches", "errors")


def merge_rows(previous, incoming, checked_at, prefer_registration=False):
    for row in incoming:
        key = row["repo"].lower(), row["packagePath"]
        old = previous.get(key, {})
        current = {**row, "observedAt": row.get("observedAt", checked_at)}
        # A failed or unrecognized registration in a new pass cannot erase pinned evidence.
        if prefer_registration and bool(old.get("registration")) != bool(current.get("registration")):
            best = old if old.get("registration") else current
        else:
            best = old if old.get("observedAt", "") > current["observedAt"] else current
        sources = sorted(set(old.get("sources", ())) | set(row.get("sources", ())))
        previous[key] = {**best, "sources": sources}


def combine(reports):
    runs = []
    matches = {}
    web = {}
    for report in sorted(reports, key=lambda report: report["checkedAt"]):
        for run in report.get("runs", [{key: report[key] for key in REPORT_FIELDS if key in report}]):
            if run not in runs:
                runs.append(run)
        merge_rows(matches, report.get("matches", []), report["checkedAt"], prefer_registration=True)
        merge_rows(web, report.get("webCandidates", []), report["checkedAt"])

    return {
        "checkedAt": max(report["checkedAt"] for report in reports),
        "repositoriesInspected": max(run["repositoriesInspected"] for run in runs),
        "repositoryCountScope": "largest individual inspection pass",
        "counts": dict(Counter("registered" if row.get("registration") else "manifest" for row in matches.values())),
        "runs": sorted(runs, key=lambda run: run["checkedAt"]),
        "matches": [matches[key] for key in sorted(matches)],
        "webCandidates": [web[key] for key in sorted(web)],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path, nargs="+")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    merged = combine([json.loads(path.read_text()) for path in args.reports])
    scratch = args.output.with_suffix(".tmp")
    scratch.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n")
    scratch.replace(args.output)
    print(json.dumps({
        **merged["counts"], "candidateWebPackages": len(merged["webCandidates"]), "recordedPasses": len(merged["runs"]),
    }))


if __name__ == "__main__":
    main()
