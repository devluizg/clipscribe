#!/usr/bin/env python3
"""Promote selected local ClipScribe clips into the public Pages library."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
LOCAL_MANIFEST = ROOT / "clips" / "manifest.json"
PUBLIC_ROOT = ROOT / "public"
PUBLIC_MEDIA = PUBLIC_ROOT / "clips"
PUBLIC_MANIFEST = PUBLIC_ROOT / "manifest.json"
MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_SITE_BYTES = 950 * 1024 * 1024


def is_remote(url: str) -> bool:
    return urlparse(url).scheme in {"http", "https"}


def copy_asset(url: str) -> str:
    if is_remote(url):
        return url
    source = (ROOT / url).resolve()
    if not source.is_file() or ROOT not in source.parents:
        raise SystemExit(f"Arquivo não encontrado ou fora do projeto: {url}")
    if source.stat().st_size > MAX_FILE_BYTES:
        raise SystemExit(f"{source.name} ultrapassa 100 MB e não pode ser publicado no GitHub comum.")
    PUBLIC_MEDIA.mkdir(parents=True, exist_ok=True)
    destination = PUBLIC_MEDIA / source.name
    shutil.copy2(source, destination)
    return f"clips/{destination.name}"


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Adiciona clipes locais à biblioteca pública")
    parser.add_argument("--id", action="append", default=[], help="ID do clipe; pode ser repetido")
    parser.add_argument("--group", action="append", default=[], help="groupId do episódio; pode ser repetido")
    parser.add_argument("--list", action="store_true", help="lista os clipes e grupos disponíveis")
    return parser.parse_args()


def main() -> None:
    args = arguments()
    local = json.loads(LOCAL_MANIFEST.read_text(encoding="utf-8")).get("clips", [])
    if args.list:
        for clip in local:
            group = f" | grupo: {clip['groupId']}" if clip.get("groupId") else ""
            print(f"{clip['id']} | {clip['title']}{group}")
        return
    if not args.id and not args.group:
        raise SystemExit("Informe --list, --id CLIP_ID ou --group GROUP_ID.")
    selected = [clip for clip in local if clip.get("id") in args.id or clip.get("groupId") in args.group]
    if not selected:
        raise SystemExit("Nenhum clipe corresponde aos IDs/grupos informados.")
    public = json.loads(PUBLIC_MANIFEST.read_text(encoding="utf-8")) if PUBLIC_MANIFEST.exists() else {"clips": []}
    entries = {clip["id"]: clip for clip in public.get("clips", [])}
    for clip in selected:
        entry = dict(clip)
        entry["videoUrl"] = copy_asset(str(clip["videoUrl"]))
        entry["subtitleUrl"] = copy_asset(str(clip["subtitleUrl"]))
        source_srt = (ROOT / str(clip["subtitleUrl"])).with_suffix(".srt")
        if source_srt.is_file():
            copy_asset(str(source_srt.relative_to(ROOT)))
        entries[str(entry["id"])] = entry
        print(f"Publicado: {entry['title']}")
    total = sum(path.stat().st_size for path in PUBLIC_ROOT.rglob("*") if path.is_file())
    if total > MAX_SITE_BYTES:
        raise SystemExit("A biblioteca pública ultrapassou o limite seguro de 950 MB.")
    ordered = sorted(entries.values(), key=lambda item: (str(item.get("groupTitle", "")), int(item.get("partNumber", 0)), str(item.get("title", ""))))
    PUBLIC_MANIFEST.write_text(json.dumps({"clips": ordered}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Biblioteca pública atualizada: {len(ordered)} clipes, {total / 1024 / 1024:.1f} MB.")


if __name__ == "__main__":
    main()
