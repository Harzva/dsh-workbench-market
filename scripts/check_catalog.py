"""Verify the static JSON/JS artifacts and public evidence link structure."""
import json
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parent.parent


def check_link(value):
    parsed = urlsplit(value)
    assert parsed.scheme == "https" and parsed.netloc == "github.com" and parsed.path.count("/") >= 2, value


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
        source = entry["source"]
        assert source in {"official", "registered", "manifest", "web", "deepseek-desktop"}, source
        assert entry["host"] == (source if source in {"web", "deepseek-desktop"} else "dataelem"), entry
        if source != "official":
            check_link(entry["manifest"])
        if source == "registered":
            check_link(entry["registration"])
        if source in {"web", "deepseek-desktop"}:
            check_link(entry["workflow"])
    print(f"{len(keys)} entries, matching JSON and browser data, valid evidence links")


if __name__ == "__main__":
    main()
