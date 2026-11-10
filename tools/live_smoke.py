"""Opt-in native-window smoke test of the approved catalog API. No contract routes."""
import argparse
import json
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from rivenscope.config import configure_logging
from rivenscope.service import Controller
from rivenscope.ui.window import MainWindow


def main():
    parser=argparse.ArgumentParser(); parser.add_argument("--directory",type=Path,required=True)
    args=parser.parse_args(); args.directory.mkdir(parents=True,exist_ok=True)
    locations={key:args.directory/key for key in ("data","state","config","cache")}
    for path in locations.values(): path.mkdir(exist_ok=True)
    configure_logging(locations["state"])
    app=QApplication([]); app.setDesktopFileName("rivenscope")
    controller=Controller(locations["data"]/"rivenscope.sqlite"); window=MainWindow(controller,locations); window.show()
    result={"platform":app.platformName(),"started_at":time.time(),"errors":[],"success":False}
    controller.error.connect(result["errors"].append)
    window.initialized.connect(window.start)
    def inspect(data):
        if data["weapons"] and data["attributes"]:
            result.update(success=True,weapons=len(data["weapons"]),attributes=len(data["attributes"]),summary=data["summary"],elapsed_seconds=time.time()-result["started_at"])
            window.nav.setCurrentRow(0)
            QTimer.singleShot(250,capture)
    captured=[False]
    def capture():
        if captured[0]: return
        captured[0]=True
        window.grab().save(str(args.directory/"dashboard.png"))
        window.nav.setCurrentRow(1); window.catalog_table.search.setText("Torid")
        window.catalog_table.view.setCurrentIndex(window.catalog_table.proxy.index(0,0))
        QTimer.singleShot(250,finish)
    def finish():
        window.grab().save(str(args.directory/"catalog.png")); window.close()
    controller.updated.connect(inspect)
    controller.ready.connect(inspect)
    QTimer.singleShot(130000,window.close)
    app.exec()
    result["worker_stopped"]=not controller.thread.isRunning()
    (args.directory/"report.json").write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps(result,indent=2))
    return 0 if result["success"] and result["worker_stopped"] and not result["errors"] else 1


if __name__=="__main__": raise SystemExit(main())
