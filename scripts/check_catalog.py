"""Verify the static JSON/JS artifacts and public evidence link structure."""
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote, urlsplit
from update_catalog import screenshot_preview

ROOT = Path(__file__).resolve().parent.parent


def check_link(value):
    parsed = urlsplit(value)
    assert parsed.scheme == "https" and parsed.netloc == "github.com" and parsed.path.count("/") >= 2, value


def pinned_link(url, repo=None):
    check_link(url)
    match = re.fullmatch(r"/([^/]+/[^/]+)/blob/([a-f0-9]{40})/(.+)", urlsplit(url).path)
    assert match and (repo is None or match[1].lower() == repo), url
    return match[2], unquote(match[3])


def main():
    exclusions = json.loads((ROOT / "catalog-exclusions.json").read_text())
    for row in exclusions:
        if "observedAt" not in row:
            continue
        revision, path = pinned_link(row["evidence"], row["repo"])
        assert revision == row["commit"] and row["source"] in {"web", "deepseek-desktop"}, row
        assert datetime.fromisoformat(row["observedAt"]).tzinfo is not None, row
        assert row["version"] and row["reason"], row
        if "upstreamEvidence" in row:
            _, upstream_path = pinned_link(row["upstreamEvidence"])
            assert path == row["packagePath"] and Path(upstream_path).name == "package.json", row
            assert re.fullmatch(r"[a-f0-9]{40}", row["packageTree"]), row
    raw = (ROOT / "dist" / "index.json").read_text()
    prefix = "window.workbenchCatalog = "
    assert (ROOT / "dist" / "catalog.js").read_text() == prefix + raw.rstrip() + ";\n"
    entries = json.loads(raw)["entries"]
    assert entries
    keys = set()
    for entry in entries:
        key = (entry["repo"], entry["package"], entry["host"])
        assert key not in keys, key
        keys.add(key)
        check_link(entry["href"])
        if "preview" in entry:
            preview = entry["preview"]
            assert screenshot_preview([preview], entry["repo"]) == preview, preview
            assert isinstance(preview["alt"], str), preview
        source = entry["source"]
        assert source in {"official", "registered", "manifest", "web", "deepseek-desktop", "dataelem-extension"}, source
        assert entry["host"] == (source if source in {"web", "deepseek-desktop"} else "dataelem"), entry
        if source != "official":
            revision, path = pinned_link(entry["manifest"], entry["repo"])
            assert path == entry["packagePath"], entry["manifest"]
            for field in ("registration", "workflow"):
                if entry[field]:
                    evidence_revision, _ = pinned_link(entry[field], entry["repo"])
                    assert evidence_revision == revision, entry[field]
            if "assembly" in entry:
                assembly_revision, _ = pinned_link(entry["assembly"], entry["repo"])
                assert source in {"web", "deepseek-desktop"} and assembly_revision == revision, entry["assembly"]
                assert entry["registration"] and entry["workflow"], entry
            if source != "manifest":
                assert entry["registration" if source == "registered" else "workflow"], entry
    previews = sum("preview" in entry for entry in entries)
    print(f"{len(keys)} entries with {previews} previews, matching JSON and browser data, valid evidence links")


if __name__ == "__main__":
    main()
