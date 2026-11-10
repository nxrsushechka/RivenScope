"""Import an explicitly supplied real legacy response into a local profile; no HTTP."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from rivenscope.analysis import AnalysisEngine
from rivenscope.contracts import contract_key, parse_auctions, timestamp
from rivenscope.storage import Store


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--response",type=Path,required=True)
    parser.add_argument("--weapon",required=True)
    parser.add_argument("--observed-at",required=True,help="Original capture time including timezone, not import time")
    parser.add_argument("--profile",type=Path,required=True)
    parser.add_argument("--weapons",type=Path,help="Explicitly supplied WFM weapon manifest, if this profile lacks a catalog")
    parser.add_argument("--attributes",type=Path,help="Explicitly supplied WFM attribute manifest")
    args=parser.parse_args()
    observed=timestamp(args.observed_at)
    if args.response.stat().st_size > 4*1024*1024: parser.error("Response exceeds 4 MiB")
    payload=json.loads(args.response.read_bytes())
    store=Store(args.profile/"data/rivenscope.sqlite")
    try:
        latest=store.db.execute("SELECT MAX(at) FROM observations WHERE weapon=?",(args.weapon,)).fetchone()[0]
        if latest is not None and observed < latest:
            raise ValueError("Snapshot predates the latest observation; use a separate profile")
        catalogs={kind:json.loads(path.read_bytes())["data"] if path else store.catalog(kind)
                  for kind,path in (("weapons",args.weapons),("attributes",args.attributes))}
        rows=parse_auctions(payload,args.weapon,observed,{w["slug"]:w for w in catalogs["weapons"]},
                            {a["slug"]:a for a in catalogs["attributes"]})
        # Validate parsing before persisting supplied manifests or observations.
        for kind in ("weapons","attributes"):
            if getattr(args,kind): store.save_catalog(kind,catalogs[kind],observed)
        result=AnalysisEngine(store).observe(rows,contract_key(args.weapon),observed,complete=False,weapon=args.weapon)
        print(json.dumps({"database":str(store.path),"records":len(rows),"events":len(result["events"]),
                          "notifications":len(result["notifications"]),"complete":False,
                          "integrity":store.db.execute("PRAGMA integrity_check").fetchone()[0]},indent=2))
    finally: store.close()


if __name__=="__main__": main()
