"""
collect_parcel_downloads.py  --  helper for Phase 4

Moves finished TxGIO parcel zips from the Downloads folder into
data/raw/parcels/parcels_<fips>.zip. Browser downloads can land under a
temporary name, so each file is identified by the county FIPS inside the zip
and its size is checked against data/seed/parcel_downloads.csv.
Usage: python scripts/collect_parcel_downloads.py <downloads folder>
"""
import re
import shutil
import sys
import zipfile
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[1]
dest = REPO / "data" / "raw" / "parcels"
dest.mkdir(parents=True, exist_ok=True)
sizes = pd.read_csv(REPO / "data/seed/parcel_downloads.csv", dtype={"county_fips": str}).set_index("county_fips")["filesize_bytes"]

src = Path(sys.argv[1])
moved = 0
for f in list(src.glob("*.tmp")) + list(src.glob("*landparcels*.zip")):
    try:
        names = zipfile.ZipFile(f).namelist()
    except Exception:
        continue                                     # still downloading, or not a zip
    m = re.search(r"landparcels_(\d{5})_", " ".join(names))
    if not m:
        continue
    fips = m.group(1)
    if f.stat().st_size != sizes.get(fips, -1):
        continue
    part = dest / f"parcels_{fips}.zip.part"
    try:
        shutil.copyfile(f, part)                     # copy then rename, so an
        part.replace(dest / f"parcels_{fips}.zip")   # interrupted copy never
        f.unlink()                                   # looks like a finished zip
    except FileNotFoundError:
        continue                                     # browser renamed it mid-copy
    moved += 1
bad = [z.name for z in dest.glob("parcels_*.zip")
       if z.stat().st_size != sizes.get(z.stem.split("_")[1], -1)]
if bad:
    print("WRONG SIZE (delete and re-download):", bad)
bad = [z.name for z in dest.glob("parcels_*.zip")
       if z.stat().st_size != sizes.get(z.stem.split("_")[1], -1)]
if bad:
    print("WRONG SIZE (delete and re-download):", bad)
print(f"moved {moved}; now have {len(list(dest.glob('parcels_*.zip')))} county zips")
