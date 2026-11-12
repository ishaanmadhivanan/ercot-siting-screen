"""Shared paths and small helpers for the website build scripts."""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import numpy as np
import shapely
from pyproj import Transformer

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
RAWWEB = RAW / "web"
PROC = REPO / "data" / "processed"
WORK = PROC / "web"            # intermediate files (not in git)
SEED = REPO / "data" / "seed"
OUT = REPO / "web" / "data"    # what the website loads (in git)
for d in (WORK, OUT):
    d.mkdir(parents=True, exist_ok=True)

METERS_PER_MILE = 1609.344
SQM_PER_ACRE = 4046.8564224

# Texas Centric Albers Equal Area (EPSG:3083): metres, good for distance and area statewide.
_TO_ALBERS = Transformer.from_crs("EPSG:4326", "EPSG:3083", always_xy=True)


def to_albers(geoms):
    """Longitude/latitude shapes -> EPSG:3083 (metres)."""
    return shapely.transform(geoms, lambda xy: np.column_stack(_TO_ALBERS.transform(xy[:, 0], xy[:, 1])))


def read_sql_export() -> list[dict]:
    """Rows saved from sql/05_export/30_export_web.sql (one JSON object per line)."""
    path = PROC / "web_export.csv"
    rows = []
    for ln in path.read_text(encoding="utf-8-sig").splitlines():
        ln = ln.strip()
        if not ln or ln == "line":
            continue
        if ln.startswith('"') and ln.endswith('"'):      # SSMS quotes the cell and doubles the quotes
            ln = ln[1:-1].replace('""', '"')
        rows.append(json.loads(ln))
    return rows


def write_json(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
    print(f"  {path.relative_to(REPO)}  {path.stat().st_size / 1e6:.2f} MB")


def tippecanoe(out: Path, args: list[str]) -> None:
    """Build a PMTiles file. tippecanoe comes from `pip install tippecanoe`."""
    env = dict(os.environ)
    env["PATH"] = str(Path.home() / ".local" / "bin") + os.pathsep + env.get("PATH", "")
    # Build on the local disk first: tippecanoe needs a file system with locking.
    tmp = Path.home() / "tiles_tmp"
    tmp.mkdir(exist_ok=True)
    local = tmp / out.name
    if local.exists():
        local.unlink()
    cmd = ["tippecanoe", "-o", str(local), "--force", "--quiet", "-t", str(tmp)] + args
    subprocess.run(cmd, check=True, env=env)
    out.write_bytes(local.read_bytes())
    local.unlink()
    print(f"  {out.relative_to(REPO)}  {out.stat().st_size / 1e6:.2f} MB")
