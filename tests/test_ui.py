"""Native Qt UI tests with recorded catalog data and explicitly controlled transport."""
import json
import tempfile
import time
from pathlib import Path
import unittest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from rivenscope.service import Controller
from rivenscope.storage import Store, new_watchlist
from rivenscope.ui.window import MainWindow
from rivenscope.ui.filters import FilterBuilder, ConditionDialog
from rivenscope.ui.preferences import WatchlistDialog
from rivenscope.ui.widgets import Table
from .test_integration import APP, wait_for, ControlledTransport, FIXTURES


class UITests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="rivenscope-ui-",dir="/tmp/opencode")
        self.locations={key:Path(self.temp.name)/key for key in ("data","state","config","cache")}
        for path in self.locations.values(): path.mkdir()
        self.db=self.locations["data"]/"rivenscope.sqlite"; store=Store(self.db)
        for kind in ("weapons","attributes"): store.save_catalog(kind,json.loads((FIXTURES/(kind+".json")).read_text())["data"],time.time())
        store.close()
        self.transport=ControlledTransport(delay=5000)
        self.controller=Controller(self.db,transport=self.transport)
        self.window=MainWindow(self.controller,self.locations); self.window.show()
        self.assertTrue(wait_for(lambda:self.window.ready))

    def tearDown(self):
        self.window.close(); self.assertTrue(wait_for(lambda:not self.controller.thread.isRunning()))
        APP.processEvents(); self.temp.cleanup()

    def test_navigation_catalog_and_source_truth(self):
        self.assertEqual(self.window.catalog_table.model.rowCount(),420)
        self.assertEqual(self.window.market_table.model.rowCount(),0)
        self.assertIn("unavailable",self.window.banner.text())
        for index in range(6):
            self.window.nav.setCurrentRow(index); APP.processEvents(); self.assertEqual(self.window.stack.currentIndex(),index)
        self.window.nav.setCurrentRow(1)
        self.window.catalog_table.search.setText("Torid")
        self.assertEqual(self.window.catalog_table.proxy.rowCount(),1)
        index=self.window.catalog_table.proxy.index(0,0); self.window.catalog_table.view.setCurrentIndex(index)
        self.assertIn("Torid",self.window.catalog_details.toPlainText())
        self.assertFalse(self.window.trade_buttons[-1].isEnabled())

    def test_watchlist_visual_builder_roundtrip(self):
        dialog=WatchlistDialog(self.window.data["weapons"],self.window.data["attributes"],self.window.data["settings"],parent=self.window)
        dialog.name.setText("Torid candidate")
        expression={"op":"AND","children":[{"field":"weapon","op":"eq","value":"torid"},{"op":"NOT","children":[{"field":"negative.zoom","op":"exists"}]}]}
        dialog.builder.set_expression(expression); self.assertEqual(dialog.builder.expression(),expression)
        dialog.save(); self.assertIsNotNone(dialog.result_value)
        results=[]; self.controller.submit("watchlist",dialog.result_value,results.append)
        self.assertTrue(wait_for(lambda:results)); self.window.refresh_data(results[0]); self.assertEqual(self.window.watchlist_table.model.rowCount(),1)

    def test_start_stop_and_close_cancel(self):
        QTest.mouseClick(self.window.start_button,Qt.MouseButton.LeftButton)
        self.assertTrue(wait_for(lambda:self.transport.pending is not None))
        self.assertTrue(self.window.stop_button.isEnabled())
        QTest.mouseClick(self.window.stop_button,Qt.MouseButton.LeftButton)
        self.assertFalse(self.controller.scheduler.running); self.assertIsNone(self.transport.pending)
        self.window.start(); self.window.close()
        self.assertTrue(wait_for(lambda:not self.controller.thread.isRunning()))
        self.assertFalse(self.controller.scheduler.timer.isActive())

    def test_virtual_table_100000_rows_and_filter(self):
        table=Table([("Number",lambda r:r["number"]),("Name",lambda r:r["name"])])
        rows=[{"number":i,"name":f"Controlled row {i}"} for i in range(100000)]
        start=time.monotonic(); table.model.set_rows(rows); table.resize(800,400); table.show(); APP.processEvents()
        self.assertLess(time.monotonic()-start,2)
        self.assertEqual(table.model.rowCount(),100000)
        table.search.setText("Controlled row 99999"); APP.processEvents(); self.assertEqual(table.proxy.rowCount(),1)
        table.close()

    def test_settings_profile_and_window_resize(self):
        prefs=self.window.preferences; prefs.controls["risk_profile"].setCurrentText("Conservative")
        self.assertEqual(prefs.values()["risk_thresholds"]["confidence"],75)
        for width,height in ((900,600),(1920,1080),(1280,720)):
            self.window.resize(width,height); APP.processEvents(); self.assertTrue(self.window.isVisible())
