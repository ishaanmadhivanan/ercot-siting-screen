"""Check the generated .Report folder against Microsoft's published schemas.
    pip install jsonschema referencing
    python scripts/validate_powerbi_report.py powerbi/ercot_siting_v2.Report
"""
import json, sys, os, glob, subprocess
from jsonschema import Draft7Validator
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT7, DRAFT202012
cache = os.path.join(os.path.expanduser("~"), ".pbi_schema_cache"); os.makedirs(cache, exist_ok=True)
def retrieve(uri):
    p = os.path.join(cache, uri.replace("://","_").replace("/","_"))
    if not os.path.exists(p):
        subprocess.run(["curl","-sS","-m","60","-o",p,uri],check=True)
    d = json.load(open(p))
    return Resource.from_contents(d, default_specification=DRAFT7)
reg = Registry(retrieve=retrieve)
def schema_for(doc):
    return doc["$schema"]
root = sys.argv[1]
bad = 0
n = 0
for f in glob.glob(root + "/**/*.json", recursive=True):
    if "StaticResources" in f or f.endswith(".pbir") : continue
    d = json.load(open(f))
    s = d.get("$schema")
    if not s: continue
    sch = retrieve(s).contents
    v = Draft7Validator(sch, registry=reg)
    errs = sorted(v.iter_errors(d), key=lambda e: list(e.path))
    n += 1
    if errs:
        bad += 1
        print("FAIL", f)
        for e in errs[:5]:
            print("   ", list(e.path), e.message[:200])
print("checked", n, "bad", bad)
