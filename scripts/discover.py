"""Search public sources and collect DSH Desktop workbench evidence without loading plugin code."""
import argparse
import concurrent.futures
import datetime as dt
import json
import re
import subprocess
import sys
import time
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
    'topic:dsh-plugin worktable in:readme',
    'topic:dsh-plugin 工作臺 in:readme',
    '"DeepSeek Harness" worktable in:readme',
    '"DeepSeek Harness" studio in:name,description',
    '"DeepSeek Harness" dashboard in:name,description',
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
    for attempt in range(2):
        result = subprocess.run(
            ["gh", "api", "--include", target],
            text=True, capture_output=True, timeout=35,
        )
        headers, _, body = result.stdout.partition("\n\n")
        if not result.returncode:
            return json.loads(body)
        problem = result.stderr.strip() or "GitHub API request failed"
        if attempt or "rate limit" not in problem.lower():
            raise RuntimeError(problem)
        reset = re.search(r"(?mi)^x-ratelimit-reset:\s*(\d+)", headers)
        retry = re.search(r"(?mi)^retry-after:\s*(\d+)", headers)
        delay = int(retry.group(1)) if retry else int(reset.group(1)) - int(time.time()) if reset else 10
        if delay > 75:
            raise RuntimeError(problem)
        time.sleep(max(1, delay + 1))


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


def bundle_has_patch(bundle):
    if not isinstance(bundle, dict):
        return False
    patch = bundle.get("patch")
    paths = patch if isinstance(patch, list) else [patch]
    return bool(paths) and all(clean_path(path) for path in paths)


def client_entry(package):
    exports = package.get("exports")
    if not isinstance(exports, dict):
        return None
    entry = exports.get("./client")
    if isinstance(entry, dict):
        entry = entry.get("default")
    return clean_path(entry)


def manifest_contract(package):
    dsh = package.get("dsh")
    if not isinstance(dsh, dict):
        return None
    client, bundle = dsh.get("client"), dsh.get("bundle")
    if not isinstance(client, dict):
        return None
    inject = client.get("inject")
    entry = client_entry(package)
    if not isinstance(inject, list) or SERVICE not in inject or not entry or not bundle_has_patch(bundle):
        return None
    if not all(isinstance(package.get(key), str) and package[key] for key in ("name", "version")):
        return None
    return entry


JS_MESSAGE = re.compile(
    r"""//[^\n]*|/\*[\s\S]*?\*/|"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'|`(?:\\[\s\S]|[^`\\])*`"""
)
SERVICE_NAME = """['"]desktopWorkbenches['"]"""
SERVICE_EXPRESSION = (
    rf"(?:\bdesktopWorkbenches\b|\[\s*{SERVICE_NAME}\s*\]"
    rf"|\bget\s*\(\s*{SERVICE_NAME}\s*\)|\bdesktopWorkbenchesOf\s*\([^)]*\))"
)


def registration_line(source):
    def mask(match):
        value = match.group()
        if value in ('"desktopWorkbenches"', "'desktopWorkbenches'", '"register"', "'register'"):
            return value
        return re.sub(r"[^\n]", " ", value)

    # Match direct service accesses and locally assigned aliases outside comments and strings.
    code = JS_MESSAGE.sub(mask, source)
    aliases = re.findall(
        rf"(?<![.\w$])([\w$]+)\s*=\s*(?:[\w$]+\s*\??\.\s*|[\w$]+(?=\s*\[)\s*)?"
        rf"{SERVICE_EXPRESSION}(?!\s*\??\.\s*register\b)",
        code,
    )
    aliases += re.findall(r"\{[^{}]*?\bdesktopWorkbenches\s*:\s*([\w$]+)[^{}]*\}\s*=", code)
    alias_pattern = "".join("|" + re.escape(item) + r"(?![\w$])" for item in sorted(set(aliases)))
    match = re.search(
        rf"(?<![\w$])(?:{SERVICE_EXPRESSION}{alias_pattern})"
        r"""\s*(?:\??\.\s*register\b|(?:\?\.)?\s*\[\s*['"]register['"]\s*\])\s*\(""", code
    )
    return code.count("\n", 0, match.start()) + 1 if match else None


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


def discussion_export(path):
    """Read project links from the official plugin showcase, including linked monorepo packages."""
    candidates = {}
    discussions = set()
    for line in path.read_text().splitlines():
        row = json.loads(line)
        number = row["number"]
        if number in discussions:
            continue
        discussions.add(number)
        for url in re.findall(r"https?://(?:www\.)?github\.com/[\w./@+%-]+", row["body"] or "", re.ASCII):
            repo = repo_id(url.rstrip("./"))
            if not repo or repo.lower() == "deepseek-ai/deepseek-harness":
                continue
            entry = candidates.setdefault(repo.lower(), {
                "repo": repo, "ref": "HEAD", "sources": set(), "paths": {"package.json": set()},
            })
            entry["sources"].add(f"DeepSeek Harness discussion #{number}")
            parts = urllib.parse.unquote(urllib.parse.urlsplit(url).path).strip("/").split("/", 4)
            if len(parts) == 5 and parts[2] in ("tree", "blob"):
                path_hint = parts[4] if parts[2] == "blob" else parts[4] + "/package.json"
                if path_hint.endswith("/package.json") and clean_path(path_hint) == path_hint:
                    entry["paths"].setdefault(path_hint, set())
    return candidates, len(discussions)


def pages(kind, query, results, errors, per_page=100, first=None):
    fetched = 0
    try:
        for page in range(1, 11):
            data = first if page == 1 and first is not None else github(
                "search/" + kind, q=query, per_page=per_page, page=page)
            items = data["items"]
            meta = results.setdefault(query, {"matched": data["total_count"], "read": 0, "incomplete": False})
            meta["read"] += len(items)
            meta["incomplete"] |= bool(data.get("incomplete_results"))
            fetched += len(items)
            yield from items
            # A partial page can precede further results when GitHub omits individual hits.
            if not items or fetched >= min(data["total_count"], 1000):
                break
        if results[query]["matched"] > fetched:
            results[query]["incomplete"] = True
    except (OSError, RuntimeError, subprocess.TimeoutExpired, KeyError, ValueError) as error:
        errors.append({"query": query, "error": str(error)})
        results.setdefault(query, {"read": 0})["incomplete"] = True


def repository_search(query, results, errors):
    """Partition capped repository searches using non-overlapping GitHub date ranges."""
    try:
        initial = github("search/repositories", q=query, per_page=100, page=1)
    except (OSError, RuntimeError, subprocess.TimeoutExpired, KeyError, ValueError) as error:
        errors.append({"query": query, "error": str(error)})
        results[query] = {"read": 0, "incomplete": True}
        return
    if initial["total_count"] <= 1000 and not (
        initial.get("incomplete_results") and initial["total_count"] > 100
    ):
        yield from pages("repositories", query, results, errors, first=initial)
        return

    partitions = []

    def read_range(start, end):
        scoped = f"{query} created:{start}..{end}"
        try:
            page = github("search/repositories", q=scoped, per_page=100, page=1)
        except (OSError, RuntimeError, subprocess.TimeoutExpired, KeyError, ValueError) as error:
            partitions.append(scoped)
            errors.append({"query": scoped, "error": str(error)})
            results[scoped] = {"read": 0, "incomplete": True}
            return
        capped = page["total_count"] > 1000
        incomplete = page.get("incomplete_results") and page["total_count"] > 100
        if (capped and start < end) or (incomplete and (end - start).days > 7):
            split = start + (end - start) // 2
            yield from read_range(start, split)
            yield from read_range(split + dt.timedelta(days=1), end)
        else:
            partitions.append(scoped)
            yield from pages("repositories", scoped, results, errors, first=page)

    end = dt.datetime.now(dt.timezone.utc).date() + dt.timedelta(days=1)
    yield from read_range(dt.date(2008, 1, 1), end)
    read = sum(results[part]["read"] for part in partitions)
    results[query] = {
        "matched": initial["total_count"], "read": read, "partitions": len(partitions),
        "incomplete": any(results[part]["incomplete"] for part in partitions) or read < initial["total_count"],
    }


def plugin_package_path(metadata):
    directory = metadata.get("directory")
    path = clean_path(directory.rstrip("/")) if isinstance(directory, str) else None
    return f"{path}/package.json" if path else None


def inventory(existing, skip_code, all_plugin_index=False, previous=(), index_only=False, index_subpackages=False):
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

    for row in [*existing, *previous]:
        add(row["repo"], row.get("packagePath", "package.json"), source="previous catalog")
    owners = Counter(row["repo"].split("/")[0] for row in previous)
    for owner, count in sorted(owners.items()):
        if count < 3:
            continue
        try:
            for page in range(1, 51):
                repos = github(f"users/{owner}/repos", type="public", per_page=100, page=page)
                for row in repos:
                    if row.get("private") is False:
                        add(row.get("full_name"), ref=row["default_branch"], source=f"owner:{owner}")
                if len(repos) < 100:
                    break
            else:
                errors.append({"source": f"owner:{owner}", "error": "owner repository page limit reached"})
        except (OSError, RuntimeError, subprocess.TimeoutExpired, KeyError, ValueError) as error:
            errors.append({"source": f"owner:{owner}", "error": str(error)})
    index_feeds = [(PLUGIN_INDEX, "plugin index")]
    if not index_only:
        index_feeds.insert(0, (OFFICIAL_INDEX, "desktop market"))
    for url, source in index_feeds:
        try:
            index = json.loads(fetch(url, limit=24_000_000))
            rows = index["workbenches" if source == "desktop market" else "plugins"]
            indices[source] = len(rows)
            for row in rows:
                metadata = row.get("repository") or {}
                repo = repo_id(row.get("url") or metadata.get("url"))
                subpackage = plugin_package_path(metadata)
                if index_subpackages:
                    if repo and subpackage:
                        add(repo, subpackage, source=source)
                    continue
                relevant = source == "desktop market" or all_plugin_index or re.search(
                    r"workbench|worktable|工作台|工作臺|desktopWorkbenches|dshdesktop|research studio|控制台", json.dumps(
                        [row.get("name"), row.get("title"), row.get("description"), row.get("metadata")],
                        ensure_ascii=False), re.I)
                if repo and relevant:
                    add(repo, source=source)
                    if subpackage:
                        add(repo, subpackage, source=source)
        except (OSError, ValueError, AttributeError, KeyError) as error:
            errors.append({"source": source, "error": str(error)})

    if index_only:
        return candidates, searches, indices, errors
    for query in REPO_QUERIES:
        print(f"Searching GitHub repositories: {query}", file=sys.stderr, flush=True)
        for row in repository_search(query + " is:public", searches, errors):
            if row.get("private") is False:
                add(row.get("full_name"), ref=row["default_branch"], source=query)
    if not skip_code:
        for query in CODE_QUERIES:
            print(f"Searching GitHub code: {query}", file=sys.stderr, flush=True)
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


def web_signal(package):
    dsh = package.get("dsh")
    if not isinstance(dsh, dict):
        return False
    client, bundle = dsh.get("client"), dsh.get("bundle")
    return (
        isinstance(client, dict) and client.get("platform") == "web"
        and bundle_has_patch(bundle) and bool(client_entry(package))
    )


def inspect(candidate):
    repo, ref = candidate["repo"], candidate["ref"]
    matches = []
    web_candidates = []
    failures = []
    commit = None
    for path, hinted_files in sorted(candidate["paths"].items()):
        try:
            package = package_at(repo, ref, path)
            contract = manifest_contract(package) if package else None
            if not contract:
                if package and web_signal(package):
                    web_candidates.append({
                        "repo": repo, "packagePath": path, "package": package.get("name"),
                        "version": package.get("version"), "ref": ref, "sources": sorted(candidate["sources"]),
                        "description": package.get("description", ""),
                    })
                continue
            if commit is None:
                commit = github(f"repos/{repo}/commits/HEAD")["sha"]
                if not SHA.fullmatch(commit):
                    raise ValueError("invalid GitHub commit")
            package = package_at(repo, commit, path)
            contract = manifest_contract(package) if package else None
            if not contract:
                continue
            entry = contract
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
    return matches, web_candidates, failures


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "discovery.json")
    parser.add_argument("--skip-code-search", action="store_true", help="Use the repository search and indexes only.")
    parser.add_argument("--workers", type=int, default=10)
    parser.add_argument("--all-plugin-index", action="store_true",
                        help="Check every public GitHub repository linked by the general plugin index.")
    parser.add_argument("--expand-from", type=Path, help="Read a previous snapshot and also inspect related owners.")
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--only-existing", action="store_true", help="Revalidate recorded community repositories only.")
    scope.add_argument("--index-subpackages", action="store_true",
                       help="Check only subpackage paths declared in the general plugin index.")
    scope.add_argument("--plugin-index-only", action="store_true",
                       help="Check the general plugin index with no repository or code search.")
    scope.add_argument("--discussion-export", type=Path,
                       help="Inspect GitHub projects linked from an official plugin showcase JSONL export.")
    scope.add_argument("--repository-export", type=Path,
                       help="Inspect a JSON export of public repositories from external indexes.")
    args = parser.parse_args()
    if not 1 <= args.workers <= 24:
        parser.error("--workers must be between 1 and 24")
    existing = json.loads((ROOT / "community.json").read_text())
    if args.repository_export:
        exported = json.loads(args.repository_export.read_text())
        candidates = {}
        for repo, sources in exported["repositories"].items():
            if (not REPO.fullmatch(repo) or not isinstance(sources, list) or not sources
                    or not all(isinstance(source, str) and source for source in sources)):
                parser.error(f"Invalid repository export record: {repo}")
            candidate = candidates.setdefault(repo.lower(), {
                "repo": repo, "ref": "HEAD", "sources": set(), "paths": {"package.json": set()},
            })
            candidate["sources"].update(sources)
        if not candidates:
            parser.error("--repository-export is empty")
        searches, indices, errors = {}, exported["indexes"], []
    elif args.discussion_export:
        candidates, discussion_count = discussion_export(args.discussion_export)
        if not discussion_count:
            parser.error("--discussion-export is empty")
        searches, indices, errors = {}, {"DeepSeek Harness plugin discussions": discussion_count}, []
    elif args.only_existing:
        candidates = {
            row["repo"].lower(): {
                "repo": row["repo"], "ref": "HEAD", "sources": {"previous catalog"},
                "paths": {row.get("packagePath", "package.json"): set()},
            } for row in existing
        }
        searches, indices, errors = {}, {}, []
    else:
        previous = json.loads(args.expand_from.read_text())["matches"] if args.expand_from else []
        index_only = args.index_subpackages or args.plugin_index_only
        candidates, searches, indices, errors = inventory(
            [] if index_only else existing,
            args.skip_code_search, args.all_plugin_index or index_only,
            [] if index_only else previous, index_only, args.index_subpackages)
    print(f"Inspecting {len(candidates)} public repositories", file=sys.stderr, flush=True)
    matches = []
    web_candidates = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        pending = {pool.submit(inspect, row) for row in candidates.values()}
        for number, future in enumerate(concurrent.futures.as_completed(pending), 1):
            found, tentative_web, failed = future.result()
            matches.extend(found)
            web_candidates.extend(tentative_web)
            errors.extend(failed)
            if number % 100 == 0:
                print(f"{number}/{len(candidates)} inspected, {len(matches)} manifests", file=sys.stderr, flush=True)
    counts = Counter("registered" if row["registration"] else "manifest" for row in matches)
    snapshot = {
        "checkedAt": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "repositoriesInspected": len(candidates), "indexes": indices, "searches": searches,
        "manifestPathsInspected": sum(len(row["paths"]) for row in candidates.values()),
        "counts": dict(counts), "errors": sorted(errors, key=lambda row: json.dumps(row, sort_keys=True)),
        "matches": sorted(matches, key=lambda row: (row["repo"].lower(), row["packagePath"])),
        "webCandidates": sorted(web_candidates, key=lambda row: (row["repo"].lower(), row["packagePath"])),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    scratch = args.output.with_suffix(".tmp")
    scratch.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n")
    scratch.replace(args.output)
    print(json.dumps({"counts": counts, "errors": len(errors), "output": str(args.output)}))


if __name__ == "__main__":
    main()
