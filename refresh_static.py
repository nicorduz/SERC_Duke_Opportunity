"""
refresh_static.py — re-normalize static datasets after replacing raw files.
Usage: put fresh raw files in raw_files/ with these names (any date suffix ok),
then run:  python refresh_static.py
  - Cluster_Queue*.xlsx        -> duke_queue
  - *OASIS*Posting*.xlsx       -> duke_oasis
  - *Red_Zone*.xlsx            -> red_zone
  - *Restrictions*.csv         -> restrictions
  - *Contested*.csv            -> contested
  - NCwarn*.csv                -> warn_nc
  - warn_sc.csv (template)     -> warn_sc
  - Power_Generation*.csv      -> Orennia (compacted to data/)
Commit the updated parquets to GitHub; Streamlit Cloud redeploys automatically.
"""
import glob, os, pandas as pd
import parsers
from preprocess_orennia import load_and_reduce

os.makedirs("data_uploads", exist_ok=True)
RAW = "raw_files"

def save(df, name):
    for c in df.columns:
        if df[c].dtype == object: df[c] = df[c].astype(str).replace("nan", "")
    df.to_parquet(f"data_uploads/{name}.parquet", index=False)
    print(f"  {name}: {len(df)} rows")

MAP = [("*Cluster_Queue*.xlsx", "duke_queue", parsers.parse_duke_cluster_queue),
       ("*OASIS*.xlsx", "duke_oasis", parsers.parse_oasis_posting),
       ("*Red_Zone*.xlsx", "red_zone", parsers.parse_red_zone),
       ("*Restrictions*.csv", "restrictions", parsers.parse_restrictions),
       ("*Contested*.csv", "contested", parsers.parse_contested),
       ("NCwarn*.csv", "warn_nc", parsers.parse_warn_nc),
       ("warn_sc.csv", "warn_sc", parsers.parse_warn_sc)]

for pat, name, fn in MAP:
    hits = glob.glob(os.path.join(RAW, pat))
    if hits:
        print(f"Refreshing {name} from {hits[0]}"); save(fn(hits[0]), name)

oren = glob.glob(os.path.join(RAW, "Power_Generation*.csv"))
if oren:
    print(f"Compacting Orennia from {oren[0]} (takes ~1 min)")
    gdf, mdf = load_and_reduce(oren[0])
    gdf.to_parquet("data/orennia_generators.parquet", index=False)
    mdf.to_parquet("data/orennia_monthly.parquet", index=False)
    print(f"  orennia: {len(gdf)} generators, {len(mdf)} monthly rows")
print("Done. Commit data/ and data_uploads/ to GitHub to redeploy.")
