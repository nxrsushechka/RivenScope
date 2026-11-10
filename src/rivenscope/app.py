import argparse
import logging
from pathlib import Path
import signal
import sys
from PySide6.QtCore import QLockFile, QTimer
from PySide6.QtWidgets import QApplication, QMessageBox
from . import __version__
from .config import paths, configure_logging
from .service import Controller
from .ui.window import MainWindow


def main(argv=None):
    parser=argparse.ArgumentParser(description="RivenScope — local Warframe Riven research")
    parser.add_argument("--version",action="version",version=__version__)
    parser.add_argument("--sync",action="store_true",help="Start monitoring using saved settings while the window is open")
    parser.add_argument("--data-dir",type=Path,help="Isolated data directory (diagnostics/testing)")
    parser.add_argument("--smoke-seconds",type=float,default=0,help="Close cleanly after this duration (packaging diagnostics)")
    args=parser.parse_args(argv)
    if args.data_dir:
        locations={key:args.data_dir/key for key in ("data","state","config","cache")}
        for path in locations.values(): path.mkdir(parents=True,exist_ok=True,mode=0o700)
    else:
        locations=paths()
    configure_logging(locations["state"])
    app=QApplication(sys.argv[:1]); app.setApplicationName("RivenScope"); app.setOrganizationName("RivenScope")
    app.setDesktopFileName("rivenscope")
    lock=QLockFile(str(locations["data"] / "application.lock")); lock.setStaleLockTime(0)
    if not lock.tryLock(100):
        QMessageBox.information(None,"RivenScope already running","A RivenScope window already owns this data directory. Close it before starting another instance.")
        return 1
    controller=Controller(locations["data"] / "rivenscope.sqlite")
    try:
        window=MainWindow(controller,locations); window.show()
    except Exception:
        controller.shutdown()
        controller.thread.wait(30000)
        lock.unlock()
        raise
    if args.sync: window.initialized.connect(window.start)
    if args.smoke_seconds>0: QTimer.singleShot(int(args.smoke_seconds*1000),window.close)
    signal.signal(signal.SIGINT,lambda *_:window.close())
    signal.signal(signal.SIGTERM,lambda *_:window.close())
    heartbeat=QTimer(); heartbeat.timeout.connect(lambda:None); heartbeat.start(500)
    code=app.exec()
    if controller.thread.isRunning():
        controller.shutdown(); controller.thread.wait(30000)
    lock.unlock()
    return code


if __name__=="__main__":
    raise SystemExit(main())
