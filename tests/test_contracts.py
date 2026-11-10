"""Captured native WFM response; controlled mutations and local HTTP only."""
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hashlib
import json
from pathlib import Path
import tempfile
from threading import Thread
import time
import unittest
from unittest.mock import patch

from rivenscope.config import validate_settings
from rivenscope.contracts import contract_key, parse_auctions, timestamp
from rivenscope.network import Outcome, Transport, request_path, USER_AGENT
from rivenscope.service import Worker, Controller
from rivenscope.storage import Store, new_watchlist
from rivenscope.ui.window import MainWindow
from rivenscope.valuation import estimate
from .test_integration import APP, wait_for, ControlledTransport

FIXTURES=Path(__file__).parent/"fixtures/live"
CAPTURED=timestamp("2026-11-10T12:25:11+00:00")
BODY=(FIXTURES/"torid-auctions-2026-11-10.json").read_bytes()
PAYLOAD=json.loads(BODY)
CATALOGS={kind:json.loads((FIXTURES/(kind+".json")).read_text())["data"] for kind in ("weapons","attributes")}


def parse(payload=PAYLOAD):
    return parse_auctions(payload,"torid",CAPTURED,**{k:{x["slug"]:x for x in v} for k,v in CATALOGS.items()})


def seed(store):
    for kind,records in CATALOGS.items():
        store.save_catalog(kind,records,CAPTURED)
        store.cache_put(kind,records,time.time())
    store.cache_put("versions",json.loads((FIXTURES/"versions.json").read_text())["data"],time.time())


class ContractParsingTests(unittest.TestCase):
    def test_capture_integrity_and_real_auction_semantics(self):
        evidence=json.loads((FIXTURES/"torid-auctions-evidence.json").read_text())
        self.assertEqual(hashlib.sha256(BODY).hexdigest(),evidence["sha256"])
        rows=parse()
        self.assertEqual(len(rows),100)
        self.assertEqual(len({r.id for r in rows}),100)
        self.assertTrue(all(r.kind=="auction" and r.acquisition is None for r in rows))
        self.assertEqual(sum(r.highest_bid is not None for r in rows),21)
        self.assertEqual(rows[0].attributes[0].value,141.2)
        self.assertFalse(rows[0].attributes[-1].positive)
        self.assertEqual(rows[0].attributes[-1].value,-49.6)
        self.assertLess(rows[0].published_at,rows[0].observed_at)
        self.assertIsNone(rows[0].disposition)
        self.assertIsNone(rows[0].measurement)
        self.assertIsNone(estimate(rows[0],rows,CAPTURED).value)

    def test_buyout_and_direct_price_never_use_an_unconfirmed_starting_bid(self):
        data=deepcopy(PAYLOAD); row=data["payload"]["auctions"][0]
        data["payload"]["auctions"]=[row]
        row["buyout_price"]=1500
        item=parse(data)[0]
        self.assertEqual((item.kind,item.acquisition),("auction_buyout",1500))
        row["is_direct_sell"]=True
        self.assertEqual((parse(data)[0].kind,parse(data)[0].acquisition),("direct",1500))
        row["buyout_price"]=None
        self.assertIsNone(parse(data)[0].acquisition)
        row["buyout_price"]=0
        with self.assertRaises(ValueError): parse(data)

    def test_malformed_records_and_cross_weapon_responses_fail_closed(self):
        mutations=[lambda r:r.update(id="../../bad"), lambda r:r["item"].update(weapon_url_name="soma"),
                   lambda r:r.update(is_direct_sell=1), lambda r:r.update(updated="2026-11-10"),
                   lambda r:r["item"]["attributes"][0].update(value=float("nan")),
                   lambda r:r["item"]["attributes"][0].update(url_name="invented_stat"),
                   lambda r:r.update(crossplay="true")]
        for mutate in mutations:
            data=deepcopy(PAYLOAD);mutate(data["payload"]["auctions"][-1])
            with self.assertRaises(ValueError): parse(data)
        data=deepcopy(PAYLOAD);data["payload"]["auctions"].append(data["payload"]["auctions"][0])
        with self.assertRaises(ValueError): parse(data)
        for data in ({"payload":{"auctions":{}}},{"data":[]},{"error":"bad"}):
            with self.assertRaises(ValueError): parse(data)
        self.assertEqual(parse({"payload":{"auctions":[]}}),[])

    def test_known_route_and_settings_validate_scope(self):
        self.assertEqual(request_path(contract_key("torid")),"/v1/auctions/search?type=riven&weapon_url_name=torid")
        for weapon in ("https://evil.example", "torid&sort_by=x", "", "../x?query"):
            with self.assertRaises(ValueError): contract_key(weapon)
        self.assertFalse(validate_settings({})["legacy_contracts"])
        for values in ({"legacy_contracts":1},{"contract_weapons":"torid"},{"contract_weapons":["torid","torid"]},
                       {"contract_interval_minutes":0}):
            with self.assertRaises(ValueError): validate_settings(values)


class ContractWorkerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.worker=Worker(Path(self.temp.name)/"db.sqlite");self.worker.store=Store(self.worker.path)
        self.addCleanup(self.worker.store.close)
        seed(self.worker.store)
        self.worker.store.save_settings({"legacy_contracts":True})

    def receive(self,body=BODY,now=CAPTURED):
        with patch("rivenscope.service.time.time",return_value=now):
            return self.worker._execute("response",Outcome("contracts:torid",200,body))

    def test_persistence_repeat_and_partial_search_do_not_infer_removal(self):
        result=self.receive()
        self.assertTrue(result["market_changed"])
        self.assertEqual(result["notifications"],[])
        self.assertEqual(self.worker.store.summary()["listings"],100)
        self.receive(now=CAPTURED+600)
        self.assertEqual(self.worker.store.summary()["snapshots"],100)
        partial=deepcopy(PAYLOAD);partial["payload"]["auctions"].pop()
        self.receive(json.dumps(partial).encode(),CAPTURED+1200)
        self.assertTrue(all(r["listing"].status=="active" for r in self.worker.store.listings()))
        self.assertEqual(self.worker.store.summary()["searched_weapons"],1)
        self.assertEqual(self.worker.store.db.execute("SELECT COUNT(*) FROM observations WHERE complete=1").fetchone()[0],0)

    def test_invalid_response_is_atomic_and_opt_out_prevents_ingestion(self):
        data=deepcopy(PAYLOAD);data["payload"]["auctions"][-1]["id"]=data["payload"]["auctions"][0]["id"]
        with self.assertRaises(ValueError): self.receive(json.dumps(data).encode())
        self.assertEqual(self.worker.store.summary()["listings"],0)
        self.worker.store.save_settings({"legacy_contracts":False})
        self.receive()
        self.assertEqual(self.worker.store.summary()["listings"],0)
        with self.assertRaises(ValueError):
            self.worker._execute("contract_batch",{"listings":[],"query_key":"q","observed_at":CAPTURED})

    def test_scope_priority_coalescing_and_refresh_interval(self):
        for priority in (2,9):
            rule=new_watchlist();rule["weapons"]=["torid"];rule["priority"]=priority
            self.worker.store.save_watchlist(rule)
        jobs=self.worker.planned_queries(CAPTURED)
        self.assertEqual(jobs,[{"key":"contracts:torid","priority":9}])
        self.receive()
        self.assertEqual(self.worker.planned_queries(CAPTURED+599),[])
        self.assertEqual(len(self.worker.planned_queries(CAPTURED+600)),1)
        self.worker.store.save_settings({"legacy_contracts":True,"contract_weapons":["*"]})
        self.assertEqual(len(self.worker.planned_queries(CAPTURED+600)),420)
        self.worker.store.save_settings({"legacy_contracts":False})
        self.assertEqual(self.worker.planned_queries(CAPTURED+600),[])


class ContractFunctionalTests(unittest.TestCase):
    def test_real_recorded_response_over_local_qt_http_into_database_and_ui(self):
        seen=[]
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                seen.append((self.path,dict(self.headers)))
                self.send_response(200);self.send_header("Content-Type","application/json")
                self.send_header("Content-Length",str(len(BODY)));self.end_headers();self.wfile.write(BODY)
            def log_message(self,*args): pass
        server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
        thread=Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with tempfile.TemporaryDirectory() as folder:
                locations={k:Path(folder)/k for k in ("data","state","config","cache")}
                for path in locations.values():path.mkdir()
                db=locations["data"]/"rivenscope.sqlite";store=Store(db);seed(store)
                store.save_settings({"legacy_contracts":True});store.close()
                controller=Controller(db);window=MainWindow(controller,locations);window.show()
                errors=[];controller.error.connect(errors.append)
                try:
                    self.assertTrue(wait_for(lambda:window.ready))
                    with patch("rivenscope.network.BASE_URL",f"http://127.0.0.1:{server.server_port}"):
                        controller.start()
                        self.assertTrue(wait_for(lambda:window.market_table.model.rowCount()==100,seconds=15),
                                        f"Requests={seen}; errors={errors}; pending={controller.pending}; status={controller.scheduler.last_status}")
                        controller.stop()
                    self.assertEqual(seen[0][0],"/v1/auctions/search?type=riven&weapon_url_name=torid")
                    self.assertEqual({k.lower():v for k,v in seen[0][1].items()}["user-agent"],USER_AGENT)
                    self.assertTrue(all(r["estimate"].value is None for r in window.market_rows))
                    self.assertEqual(window.notification_table.model.rowCount(),0)
                    self.assertIn("1/420",window.coverage.text())
                    self.assertEqual(errors,[])
                finally:
                    window.close();controller.shutdown()
                    self.assertTrue(wait_for(lambda:not controller.thread.isRunning()))
        finally:
            server.shutdown();server.server_close();thread.join(2)
