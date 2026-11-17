"""Verify the static JSON/JS artifacts and public evidence link structure."""
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit
from update_catalog import screenshot_preview

ROOT = Path(__file__).resolve().parent.parent


def check_link(value):
    parsed = urlsplit(value)
    assert parsed.scheme == "https" and parsed.netloc == "github.com" and parsed.path.count("/") >= 2, value


def pinned_link(url, repo):
    check_link(url)
    match = re.fullmatch(r"/([^/]+/[^/]+)/blob/([a-f0-9]{40})/(.+)", urlsplit(url).path)
    assert match and match[1].lower() == repo, url
    return match[2], unquote(match[3])


def main():
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
            evidence = entry["registration"] if source == "registered" else entry["workflow"]
            if evidence:
                evidence_revision, _ = pinned_link(evidence, entry["repo"])
                assert evidence_revision == revision, evidence
            if source != "manifest":
                assert evidence, entry
    previews = sum("preview" in entry for entry in entries)
    print(f"{len(keys)} entries with {previews} previews, matching JSON and browser data, valid evidence links")


if __name__ == "__main__":
    main()
