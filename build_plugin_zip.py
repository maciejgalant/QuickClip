#!/usr/bin/env python3
"""Buduje dist/QuickClip-<wersja>.zip gotowy do wgrania na plugins.qgis.org."""
import configparser
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).parent
PLUGIN = ROOT / "QuickClip"

cfg = configparser.ConfigParser(interpolation=None)
cfg.read(PLUGIN / "metadata.txt", encoding="utf-8")
version = cfg["general"]["version"]

dist = ROOT / "dist"
dist.mkdir(exist_ok=True)
target = dist / f"QuickClip-{version}.zip"

with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
    for path in sorted(PLUGIN.rglob("*")):
        if path.is_dir() or "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
            continue
        zf.write(path, path.relative_to(ROOT))
print(f"OK: {target}")
