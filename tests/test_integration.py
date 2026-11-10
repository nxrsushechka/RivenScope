"""Qt event-loop integration and controlled network errors; no public requests."""
import json
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from pathlib import Path
import tempfile
import time
import unittest
from PySide6.QtCore import QObject, Signal, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
from rivenscope.network import Outcome
from rivenscope.scheduler import Scheduler
from rivenscope.service import Controller
from rivenscope.storage import Store

APP = QApplication.instance() or QApplication([])
FIXTURES = Path(__file__).parent / "fixtures/live"


def wait_for(predicate, seconds=3):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        APP.processEvents()
        if predicate(): return True
        QTest.qWait(5)
    return bool(predicate())


class ControlledTransport(QObject):
    finished=Signal(object)

    def __init__(self, statuses=None, delay=2):
        super().__init__(); self.calls=[]; self.statuses=list(statuses or []); self.pending=None
        self.timer=QTimer(self); self.timer.setSingleShot(True); self.timer.timeout.connect(self.complete); self.delay=delay

    def get(self,key):
        self.calls.append(key); self.pending=key; self.timer.start(self.delay)

    def complete(self):
        key=self.pending; self.pending=None
        status=self.statuses.pop(0) if self.statuses else 200
        body=(FIXTURES/(key+".json")).read_bytes() if status==200 else b""
        self.finished.emit(Outcome(key,status,body,error="Controlled network failure" if not status else ""))

    def abort(self):
        self.timer.stop()
        if self.pending:
            key,self.pending=self.pending,None; self.finished.emit(Outcome(key,0,cancelled=True))


class SchedulerIntegrationTests(unittest.TestCase):
    def test_failure_backoff_reconnection_and_stop(self):
        transport=ControlledTransport([0,200]); now=[1000.0]
        scheduler=Scheduler(transport,clock=lambda:now[0]); outcomes=[]; scheduler.outcome.connect(outcomes.append)
        scheduler.start(); scheduler.enqueue("versions"); scheduler.enqueue("versions",consumer="watchlist")
        self.assertTrue(wait_for(lambda:len(outcomes)==1)); self.assertEqual(len(transport.calls),1)
        scheduler.tick(); self.assertEqual(len(transport.calls),1)
        now[0]=scheduler.budget.cooldown+10; scheduler.tick()
        self.assertTrue(wait_for(lambda:len(outcomes)==2)); self.assertEqual(outcomes[-1].status,200)
        scheduler.stop(); self.assertFalse(scheduler.timer.isActive()); self.assertFalse(scheduler.queue.jobs)

    def test_cancel_and_repeated_start_stop(self):
        transport=ControlledTransport(delay=10000); now=[1000.0]
        scheduler=Scheduler(transport,clock=lambda:now[0]); outcomes=[]; scheduler.outcome.connect(outcomes.append)
        for _ in range(25):
            scheduler.start(); scheduler.enqueue("versions"); scheduler.stop(); now[0]+=7
            APP.processEvents()
            self.assertFalse(scheduler.running); self.assertIsNone(transport.pending)
        self.assertEqual(outcomes,[]); self.assertEqual(len(transport.calls),25)

    def test_retry_after_block_and_unknown_route(self):
        transport=ControlledTransport(delay=10000); now=[1000.0]
        scheduler=Scheduler(transport,clock=lambda:now[0]); scheduler.start(); scheduler.enqueue("versions")
        transport.timer.stop(); transport.finished.emit(Outcome("versions",429,retry_after="120"))
        now[0]=1119; scheduler.tick(); self.assertEqual(len(transport.calls),1)
        now[0]=1121; scheduler.tick(); self.assertEqual(len(transport.calls),2)
        with self.assertRaises(ValueError): scheduler.enqueue("contracts")
        scheduler.stop()


class WorkerIntegrationTests(unittest.TestCase):
    def test_worker_cache_lifecycle_and_ui_heartbeat(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as folder:
            transport=ControlledTransport(); controller=Controller(Path(folder)/"db.sqlite",transport=transport)
            ready=[]; errors=[]; controller.ready.connect(ready.append); controller.error.connect(errors.append)
            self.assertTrue(wait_for(lambda:ready))
            now=[time.time()]; controller.scheduler.clock=lambda:now[0]
            updates=[]; controller.updated.connect(updates.append)
            controller.start()
            self.assertTrue(wait_for(lambda:len(updates)>=1))
            for _ in range(2):
                now[0]+=10; controller.scheduler.tick(); self.assertTrue(wait_for(lambda:controller.scheduler.active is None))
                QTest.qWait(30)
            self.assertTrue(wait_for(lambda:updates and len(updates[-1]["attributes"])==50))
            self.assertEqual(len(updates[-1]["weapons"]),420)
            self.assertEqual(updates[-1]["summary"]["listings"],0)
            calls=len(transport.calls); controller.stop(); controller.start(); QTest.qWait(100)
            self.assertEqual(len(transport.calls),calls)  # persistent cache prevents repeated fetches
            heartbeat=[]; timer=QTimer(); timer.timeout.connect(lambda:heartbeat.append(time.monotonic())); timer.start(10)
            responses=[]
            for _ in range(50): controller.submit("analytics","",responses.append)
            self.assertTrue(wait_for(lambda:len(responses)==50)); QTest.qWait(30); timer.stop()
            self.assertGreater(len(heartbeat),0)
            controller.shutdown(); self.assertTrue(wait_for(lambda:not controller.thread.isRunning()))
            self.assertEqual(errors,[])
            store=Store(Path(folder)/"db.sqlite"); self.assertEqual(len(store.catalog("weapons")),420); store.close()

    def test_corruption_recovery_preserves_original(self):
        with tempfile.TemporaryDirectory(dir="/tmp/opencode") as folder:
            root=Path(folder); original=Store(root/"original.sqlite"); original.backup(root/"backup.sqlite"); original.close()
            damaged=root/"damaged.sqlite"; damaged.write_bytes(b"controlled corruption")
            with self.assertLogs("rivenscope.service", level="ERROR"):
                controller=Controller(damaged,transport=ControlledTransport()); errors=[]; controller.error.connect(errors.append)
                self.assertTrue(wait_for(lambda:errors))
            results=[]; controller.submit("restore",{"source":str(root/"backup.sqlite"),"confirmed":True},results.append)
            self.assertTrue(wait_for(lambda:results))
            preserved=list(root.glob("damaged-*/damaged.sqlite")); self.assertEqual(preserved[0].read_bytes(),b"controlled corruption")
            controller.shutdown(); self.assertTrue(wait_for(lambda:not controller.thread.isRunning()))
