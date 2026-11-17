"""Refresh official DSH Desktop listings and merge the checked community records."""
import argparse
import datetime
import json
import os
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL_INDEX = "https://market.dshdesktop.com/index.json"


def load_official():
    request = urllib.request.Request(OFFICIAL_INDEX, headers={"User-Agent": "dsh-catalog-research"})
    with urllib.request.urlopen(request, timeout=20) as response:
        index = json.load(response)
    if index.get("schemaVersion") != 2 or not index.get("workbenches"):
        raise ValueError("Unexpected DSH Desktop catalog schema")
    return index


def github_link(url):
    parsed = urlsplit(url) if isinstance(url, str) else None
    return url if parsed and parsed.scheme == "https" and parsed.netloc.lower() == "github.com" else ""


def build_catalog(index, community, checked_at, web=(), discoveries=()):
    categories = {item["id"]: item["name"]["zh"] for item in index["categories"]}
    entries = []
    seen_repos = set()
    seen_packages = set()
    known_repos = {item["id"].lower() for item in index["workbenches"]}
    excluded = {
        "aswang2205/dsh-xiaomi-ocr",  # Pinned client only registers a settings section.
        "weixiurui/dsh-firefly-forest",  # Theme interface.
        "nikolay-leukhin/dsh_multiagent_system_monitoring_performance_plugin",  # Duplicate of projectHub.
    }
    web_panel_replacements = {"mistyrn/dsh-experience", "narkco-kang/dsh-team-workbench"}
    for item in index["workbenches"]:
        repo = item["id"].lower()
        source = item.get("distribution") or {}
        package = source.get("package") or source.get("packageName") or ""
        description = item.get("description") or {}
        entries.append({
            "repo": repo,
            "name": item["name"],
            "nameEn": item.get("nameEn", ""),
            "description": description.get("zh") or description.get("en") or "",
            "category": categories[item["category"]],
            "version": item["version"],
            "source": "official",
            "href": github_link(item["url"]),
            "host": "dataelem",
            "identity": item.get("workbenchId"),
            "package": package,
        })
        seen_repos.add((repo, "package.json", "dataelem"))
        if package:
            seen_packages.add((package, "dataelem"))

    # Preserve reviewed labels while preferring pinned GitHub evidence.
    merged = {}
    for item in [*discoveries, *community]:
        key = (item["repo"].lower(), item.get("packagePath", "package.json"))
        previous = merged.get(key, {})
        if previous.get("commit") and (previous.get("registration") or not item.get("registration")):
            item = {**item, **{name: previous[name] for name in (
                "commit", "packagePath", "manifest", "canonicalRepo",
            ) if name in previous}}
            if previous.get("registration"):
                item["registration"] = previous["registration"]
            item["version"] = previous["version"]
        merged[key] = item

    records = [*sorted(merged.values(), key=lambda row: (
        not row.get("registration"), row["repo"].lower(), row.get("packagePath", ""),
    )), *web]
    for item in records:
        repo = item["repo"].lower()
        package = item["package"]
        canonical = (item.get("canonicalRepo") or "").lower()
        is_web = bool(item.get("workflow"))
        host = item.get("host", "web") if is_web else "dataelem"
        package_path = item.get("packagePath", "package.json")
        if repo in excluded or (not is_web and canonical in known_repos and canonical != repo):
            continue
        if not is_web and not item.get("registration") and repo in web_panel_replacements:
            continue
        identity = (repo, package_path, host)
        if identity in seen_repos or (package, host) in seen_packages:
            continue
        links = {name: github_link(item.get(name)) for name in ("manifest", "registration", "workflow")}
        source = host if is_web else "registered" if links["registration"] else "manifest"
        entries.append({
            **{key: item[key] for key in ("name", "description", "package", "version") if key in item},
            **links,
            "repo": repo,
            "category": item.get("category", "其他"),
            "host": host,
            "packagePath": package_path,
            "source": source,
            "href": github_link("https://github.com/" + item["repo"]),
        })
        seen_repos.add(identity)
        seen_packages.add((package, host))

    return {"checkedAt": checked_at, "officialIndex": OFFICIAL_INDEX, "entries": entries}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--official-file", type=Path, help="Use a previously downloaded official index.")
    parser.add_argument("--checked-at", default=datetime.date.today().isoformat())
    args = parser.parse_args()
    index = json.loads(args.official_file.read_text()) if args.official_file else load_official()
    community = json.loads((ROOT / "community.json").read_text())
    web = json.loads((ROOT / "web-workbenches.json").read_text())
    snapshot = ROOT / "discovery.json"
    discovered = json.loads(snapshot.read_text())["matches"] if snapshot.exists() else []
    catalog = build_catalog(index, community, args.checked_at, web, discovered)
    target = ROOT / "dist" / "catalog.js"
    scratch = target.with_suffix(".tmp")
    scratch.write_text("window.workbenchCatalog = " + json.dumps(catalog, ensure_ascii=False, indent=2) + ";\n")
    os.replace(scratch, target)
    json_target = ROOT / "dist" / "index.json"
    scratch = json_target.with_suffix(".tmp")
    scratch.write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n")
    os.replace(scratch, json_target)
    counts = {source: sum(row["source"] == source for row in catalog["entries"])
              for source in ("official", "registered", "web", "deepseek-desktop", "manifest")}
    print(json.dumps(counts))


if __name__ == "__main__":
    main()
