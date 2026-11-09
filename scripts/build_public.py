#!/usr/bin/env python3
"""Build the static, student-only ClipScribe site for GitHub Pages."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
PUBLIC = ROOT / "public"
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_SITE_BYTES = 950 * 1024 * 1024


def main() -> None:
    manifest_path = PUBLIC / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest.get("clips"), list):
        raise SystemExit("public/manifest.json inválido.")
    if DIST.exists():
        shutil.rmtree(DIST)
    DIST.mkdir()
    for name in ("css", "js", "sample"):
        shutil.copytree(ROOT / name, DIST / name)
    html = (ROOT / "index.html").read_text(encoding="utf-8")
    html = html.replace('name="clipscribe-mode" content="auto"', 'name="clipscribe-mode" content="public"')
    (DIST / "index.html").write_text(html, encoding="utf-8")
    shutil.copytree(PUBLIC / "clips", DIST / "clips")
    shutil.copy2(manifest_path, DIST / "clips" / "manifest.json")
    (DIST / ".nojekyll").write_text("", encoding="utf-8")
    for clip in manifest["clips"]:
        for field in ("videoUrl", "subtitleUrl"):
            url = str(clip.get(field, ""))
            if urlparse(url).scheme in {"http", "https"}:
                continue
            asset = DIST / url
            if not asset.is_file():
                raise SystemExit(f"Asset público ausente: {url}")
            if asset.stat().st_size > MAX_FILE_BYTES:
                raise SystemExit(f"{url} ultrapassa 100 MB.")
    total = sum(path.stat().st_size for path in DIST.rglob("*") if path.is_file())
    if total > MAX_SITE_BYTES:
        raise SystemExit("O site publicado ultrapassa o limite seguro de 950 MB.")
    print(f"Site público gerado em {DIST} ({len(manifest['clips'])} clipes, {total / 1024 / 1024:.1f} MB).")


if __name__ == "__main__":
    main()
