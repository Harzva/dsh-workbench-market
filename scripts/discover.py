"""Search public sources and collect DSH Desktop workbench evidence without loading plugin code."""
import argparse
import concurrent.futures
import datetime as dt
import json
import re
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OFFICIAL_INDEX = "https://market.dshdesktop.com/index.json"
PLUGIN_INDEX = "https://awesome-dsh-plugin.com/index.json"
REPO = re.compile(r"^[\w.-]+/[\w.-]+$", re.ASCII)
SHA = re.compile(r"^[a-f0-9]{40}$")
SERVICE = "dsh-desktop-workbenches"
REPO_QUERIES = (
    "topic:dsh-workbench",
    'topic:dsh-plugin workbench in:readme',
    'topic:dsh-plugin 工作台 in:readme',
    '"DSH Desktop" workbench in:readme',
    '"DSH Desktop" 工作台 in:readme',
    '"dsh-desktop-workbenches" in:readme',
    '"desktopWorkbenches" in:readme',
    '"DeepSeek Harness" workbench in:name,description',
    '"DeepSeek Harness" 工作台 in:name,description',
)
CODE_QUERIES = (
    '"dsh-desktop-workbenches" filename:package.json',
    '"desktopWorkbenches"',
    '"desktopWorkbenchesOf"',
)
SOURCE_EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx")
READ_LIMIT = 3_000_000


def fetch(url, limit=READ_LIMIT):
    request = urllib.request.Request(url, headers={"User-Agent": "dsh-catalog-research"})
    with urllib.request.urlopen(request, timeout=12) as response:
        value = response.read(limit + 1)
    if len(value) > limit:
        raise ValueError("response exceeds the file size limit")
    return value


def github(path, **params):
    target = path + ("?" + urllib.parse.urlencode(params) if params else "")
    result = subprocess.run(
        ["gh", "api", target],
        text=True, capture_output=True, timeout=35,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "GitHub API request failed")
    return json.loads(result.stdout)


def raw_url(repo, ref, path):
    base = "https://raw.githubusercontent.com/"
    return base + "/".join((repo, urllib.parse.quote(ref, safe=""), urllib.parse.quote(path)))


def clean_path(value):
    if not isinstance(value, str):
        return None
    value = value.removeprefix("./")
    if not value or any(part in ("", ".", "..") for part in value.split("/")):
        return None
    return value if re.fullmatch(r"[\w.@+ /-]+", value) else None


def manifest_contract(package):
    dsh = package.get("dsh")
    if not isinstance(dsh, dict):
        return None
    client, bundle, exports = dsh.get("client"), dsh.get("bundle"), package.get("exports")
    if not all(isinstance(field, dict) for field in (client, bundle, exports)):
        return None
    inject = client.get("inject")
    entry = exports.get("./client")
    if isinstance(entry, dict):
        entry = entry.get("default") or entry.get("import")
    entry, patch = clean_path(entry), clean_path(bundle.get("patch"))
    if not isinstance(inject, list) or SERVICE not in inject or not entry or not patch:
        return None
    if not all(isinstance(package.get(key), str) and package[key] for key in ("name", "version")):
        return None
    return entry, patch


def registration_line(source):
    # Keep line numbers intact and remove comments before searching for a call.
    source = re.sub(r"/\*[\s\S]*?\*/", lambda m: "\n" * m.group().count("\n"), source)
    source = re.sub(r"(?m)^\s*//[^\n]*", lambda m: "\n" * m.group().count("\n"), source)
    source = re.sub(r"""(?:"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')""", "", source)
    aliases = re.findall(
        r"\b([\w$]+)\s*=\s*(?:[\w$]+\.)?(?:desktopWorkbenches\b(?!\s*\.)|desktopWorkbenchesOf\s*\()",
        source,
    )
    names = "|".join(re.escape(item) for item in ["desktopWorkbenches", *aliases])
    match = re.search(r"(?<![\w$])(?:" + names + r")\s*\??\.\s*register\s*\(", source)
    return source.count("\n", 0, match.start()) + 1 if match else None


def package_at(repo, ref, path):
    try:
        data = json.loads(fetch(raw_url(repo, ref, path)))
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise
    except (UnicodeError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def find_registration(repo, ref, files):
    for path in files:
        try:
            source = fetch(raw_url(repo, ref, path)).decode("utf-8")
        except urllib.error.HTTPError as error:
            if error.code == 404:
                continue
            raise
        except (UnicodeError, ValueError):
            continue
        line = registration_line(source)
        if line:
            return f"https://github.com/{repo}/blob/{ref}/{urllib.parse.quote(path)}#L{line}"
    return None


def repo_id(url):
    if isinstance(url, str):
        url = url.removeprefix("git+")
        parsed = urllib.parse.urlparse(url)
        if parsed.hostname and parsed.hostname.lower() in ("github.com", "www.github.com"):
            parts = parsed.path.strip("/").split("/")
            if len(parts) >= 2:
                candidate = "/".join(parts[:2]).removesuffix(".git")
                return candidate if REPO.fullmatch(candidate) else None
    return None


def pages(kind, query, results, errors, per_page=100):
    fetched = 0
    try:
        for page in range(1, 11):
            data = github("search/" + kind, q=query, per_page=per_page, page=page)
            items = data["items"]
            meta = results.setdefault(query, {"matched": data["total_count"], "read": 0, "incomplete": False})
            meta["read"] += len(items)
            meta["incomplete"] |= bool(data.get("incomplete_results"))
            fetched += len(items)
            yield from items
            if len(items) < per_page or fetched >= min(data["total_count"], 1000):
                break
        if results[query]["matched"] > fetched:
            results[query]["incomplete"] = True
    except (OSError, RuntimeError, subprocess.TimeoutExpired, KeyError, ValueError) as error:
        errors.append({"query": query, "error": str(error)})
        results.setdefault(query, {"read": 0})["incomplete"] = True


def inventory(existing, skip_code):
    candidates = {}
    searches = {}
    indices = {}
    errors = []

    def add(repo, path="package.json", ref="HEAD", source=""):
        if isinstance(repo, str) and REPO.fullmatch(repo) and clean_path(path):
            key = repo.lower()
            row = candidates.setdefault(key, {"repo": repo, "ref": ref, "paths": {}, "sources": set()})
            row["paths"].setdefault(path, set())
            row["sources"].add(source)

    for row in existing:
        add(row["repo"], row.get("packagePath", "package.json"), source="previous catalog")
    for url, source in ((OFFICIAL_INDEX, "desktop market"), (PLUGIN_INDEX, "plugin index")):
        try:
            index = json.loads(fetch(url, limit=24_000_000))
            rows = index["workbenches" if source == "desktop market" else "plugins"]
            indices[source] = len(rows)
            for row in rows:
                repo_url = row.get("url") or (row.get("repository") or {}).get("url")
                repo = repo_id(repo_url)
                relevant = source == "desktop market" or re.search(
                    r"workbench|worktable|工作台|desktopWorkbenches|dshdesktop", json.dumps(
                        [row.get("name"), row.get("title"), row.get("description"), row.get("metadata")],
                        ensure_ascii=False), re.I)
                if repo and relevant:
                    add(repo, source=source)
        except (OSError, ValueError, AttributeError, KeyError) as error:
            errors.append({"source": source, "error": str(error)})

    for query in REPO_QUERIES:
        for row in pages("repositories", query + " is:public", searches, errors):
            if row.get("private") is False:
                add(row.get("full_name"), ref=row["default_branch"], source=query)
    if not skip_code:
        for query in CODE_QUERIES:
            for row in pages("code", query, searches, errors):
                repo = row.get("repository", {})
                if repo.get("private") is not False or not REPO.fullmatch(repo.get("full_name", "")):
                    continue
                path = row["path"]
                if not clean_path(path):
                    continue
                name = repo["full_name"]
                add(name, source=query)
                if path.endswith("/package.json") or path == "package.json":
                    add(name, path, source=query)
                elif path.endswith(SOURCE_EXTENSIONS) and not path.endswith(".d.ts"):
                    parent = path.rpartition("/")[0]
                    while parent:
                        manifest = parent + "/package.json"
                        add(name, manifest, source=query)
                        candidates[name.lower()]["paths"][manifest].add(path)
                        parent = parent.rpartition("/")[0]
                    candidates[name.lower()]["paths"]["package.json"].add(path)
    return candidates, searches, indices, errors


def inspect(candidate):
    repo, ref = candidate["repo"], candidate["ref"]
    matches = []
    failures = []
    commit = None
    for path, hinted_files in sorted(candidate["paths"].items()):
        try:
            package = package_at(repo, ref, path)
            contract = manifest_contract(package) if package else None
            if not contract:
                continue
            if commit is None:
                commit = github(f"repos/{repo}/commits/HEAD")["sha"]
                if not SHA.fullmatch(commit):
                    raise ValueError("invalid GitHub commit")
            package = package_at(repo, commit, path)
            contract = manifest_contract(package) if package else None
            if not contract:
                continue
            entry, patch = contract
            parent, _, _ = path.rpartition("/")
            base = parent + "/" if parent else ""
            files = list(dict.fromkeys([base + entry, *sorted(hinted_files), *(
                base + file for file in (
                    "src/client.ts", "src/client.tsx", "src/client/index.ts", "src/client/index.tsx",
                    "client.ts", "client.tsx", "client.js",
                )
            )]))
            failure = None
            try:
                registration = find_registration(repo, commit, files)
            except (OSError, ValueError) as error:
                registration = None
                failure = str(error)
            origin = package.get("repository")
            origin = origin.get("url") if isinstance(origin, dict) else origin
            row = {
                "repo": repo, "commit": commit, "packagePath": path,
                "package": package["name"], "version": package["version"],
                "name": package.get("displayName") or package["name"],
                "description": package.get("description", "") if isinstance(package.get("description"), str) else "",
                "manifest": f"https://github.com/{repo}/blob/{commit}/{urllib.parse.quote(path)}",
                "registration": registration,
                "canonicalRepo": repo_id(origin), "sources": sorted(candidate["sources"]),
            }
            matches.append(row)
            if failure:
                failures.append({"repo": repo, "path": path, "error": failure})
        except (OSError, RuntimeError, subprocess.TimeoutExpired, KeyError, ValueError) as error:
            failures.append({"repo": repo, "path": path, "error": str(error)})
    return matches, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "discovery.json")
    parser.add_argument("--skip-code-search", action="store_true", help="Use the repository search and indexes only.")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--only-existing", action="store_true", help="Revalidate recorded community repositories only.")
    args = parser.parse_args()
    if not 1 <= args.workers <= 24:
        parser.error("--workers must be between 1 and 24")
    existing = json.loads((ROOT / "community.json").read_text())
    if args.only_existing:
        candidates = {
            row["repo"].lower(): {
                "repo": row["repo"], "ref": "HEAD", "sources": {"previous catalog"},
                "paths": {row.get("packagePath", "package.json"): set()},
            } for row in existing
        }
        searches, indices, errors = {}, {}, []
    else:
        candidates, searches, indices, errors = inventory(existing, args.skip_code_search)
    print(f"Inspecting {len(candidates)} public repositories", file=sys.stderr, flush=True)
    matches = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(inspect, row) for row in candidates.values()}
        for number, future in enumerate(concurrent.futures.as_completed(pending), 1):
            found, failed = future.result()
            matches.extend(found)
            errors.extend(failed)
            if number % 100 == 0:
                print(f"{number}/{len(candidates)} inspected, {len(matches)} manifests", file=sys.stderr, flush=True)
    counts = Counter("registered" if row["registration"] else "manifest" for row in matches)
    snapshot = {
        "checkedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "repositoriesInspected": len(candidates), "indexes": indices, "searches": searches,
        "counts": dict(counts), "errors": sorted(errors, key=lambda row: json.dumps(row, sort_keys=True)),
        "matches": sorted(matches, key=lambda row: (row["repo"].lower(), row["packagePath"])),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scratch = args.output.with_suffix(".tmp")
    scratch.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    scratch.replace(args.output)
    print(json.dumps({"counts": counts, "errors": len(errors), "output": str(args.output)}))


if __name__ == "__main__":
    main()
