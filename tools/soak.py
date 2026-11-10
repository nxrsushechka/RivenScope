"""Controlled timed soak. Synthetic observations remain in an isolated test directory."""
import argparse
from dataclasses import replace
import json
from pathlib import Path
import resource
import statistics
import sys
import tempfile
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from rivenscope.storage import Store
from rivenscope.service import Controller
from rivenscope.ui.window import MainWindow
from tests.helpers import listing
from tests.test_integration import APP, ControlledTransport, FIXTURES


def rss():
    for line in Path("/proc/self/status").read_text().splitlines():
        if line.startswith("VmRSS:"): return int(line.split()[1])/1024


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--seconds",type=int,default=180); parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args(); root=Path(tempfile.mkdtemp(prefix="rivenscope-soak-"))
    locations={key:root/key for key in ("data","state","config","cache")}
    for path in locations.values(): path.mkdir()
    db=locations["data"]/"rivenscope.sqlite"; store=Store(db); now=time.time()
    for key in ("weapons","attributes"):
        store.save_catalog(key,json.loads((FIXTURES/(key+".json")).read_text())["data"],now)
    sample=[listing(f"soak-{i}",price=500+i%50,observed_at=now,weapon=f"controlled_weapon_{i//20}") for i in range(400)]
    store.observe(sample,"controlled-only",now,complete=True)
    for step in range(1,8): store.observe([replace(s,price=s.price+step,observed_at=now+step) for s in sample],"controlled-only",now+step,complete=True)
    store.close()
    transport=ControlledTransport(delay=5); controller=Controller(db,transport=transport); window=MainWindow(controller,locations); window.show()
    start=time.monotonic(); cpu_start=time.process_time(); beats=[]; memory=[]; errors=[]; cycles=[0]; processed=[0]; outstanding=[False]
    controller.error.connect(errors.append)
    beat=QTimer(); beat.setInterval(20); beat.timeout.connect(lambda:beats.append(time.monotonic())); beat.start()
    tick=QTimer(); tick.setInterval(250)
    def step():
        if not window.ready: return
        cycles[0]+=1
        if cycles[0]%4==0:
            memory.append((time.monotonic()-start,rss()))
            window.nav.setCurrentRow((cycles[0]//4)%6)
        if cycles[0]%12==0:
            controller.start(); QTimer.singleShot(20,controller.stop)
        if not outstanding[0]:
            outstanding[0]=True
            def loaded(rows):
                outstanding[0]=False; processed[0]+=1; window.market_loaded(rows)
            controller.submit("market",{},loaded)
    tick.timeout.connect(step); tick.start()
    QTimer.singleShot(args.seconds*1000,window.close)
    APP.exec(); beat.stop(); tick.stop()
    gaps=[b-a for a,b in zip(beats,beats[1:])]
    warm=[m for t,m in memory if t>min(30,args.seconds/3)]
    result={"controlled_data_only":True,"duration_seconds":time.monotonic()-start,"cycles":cycles[0],"market_refreshes":processed[0],
            "cpu_seconds":time.process_time()-cpu_start,"rss_start_mb":memory[0][1] if memory else 0,"rss_end_mb":rss(),
            "rss_warm_growth_mb":(max(warm)-min(warm)) if warm else 0,"heartbeat_max_gap_ms":max(gaps,default=0)*1000,
            "heartbeat_p99_gap_ms":sorted(gaps)[int(len(gaps)*.99)]*1000 if gaps else 0,
            "worker_stopped":not controller.thread.isRunning(),"errors":errors,"directory":str(root)}
    args.output.parent.mkdir(parents=True,exist_ok=True); args.output.write_text(json.dumps(result,indent=2)+"\n"); print(json.dumps(result,indent=2))
    return 0 if not errors and result["worker_stopped"] and result["rss_warm_growth_mb"]<40 and result["heartbeat_p99_gap_ms"]<200 else 1


if __name__=="__main__": raise SystemExit(main())
