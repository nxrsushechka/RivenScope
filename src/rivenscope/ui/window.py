from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import statistics
import time
import uuid
from PySide6.QtCore import Qt, QSettings, QUrl, QTimer, Signal
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (QMainWindow, QWidget, QFrame, QHBoxLayout, QVBoxLayout,
    QGridLayout, QListWidget, QStackedWidget, QTabWidget, QTextBrowser, QSplitter,
    QComboBox, QMessageBox, QFileDialog, QScrollArea, QDialog, QDialogButtonBox,
    QApplication, QGroupBox)
from .. import __version__, CONTRACT_LIMITATION
from ..config import DEFAULTS
from ..domain import safe_market_url, MARKET_PAGE_SIZE
from ..filters import validate
from ..notifications import Channels
from .widgets import STYLE, Metric, Table, Chart, label, button, page
from .filters import FilterBuilder
from .preferences import Preferences, WatchlistDialog


def timestamp(value):
    return datetime.fromtimestamp(value, timezone.utc).strftime("%Y-%m-%d %H:%M UTC") if value else "Never"


def age(value):
    if not value: return "Unknown"
    delta = max(0, time.time()-value)
    return f"{delta/86400:.1f}d" if delta >= 86400 else f"{delta/3600:.1f}h" if delta >= 3600 else f"{delta/60:.0f}m"


class MainWindow(QMainWindow):
    initialized = Signal()

    def __init__(self, controller, locations):
        super().__init__()
        self.controller, self.locations = controller, locations
        self.data = {"settings": deepcopy(DEFAULTS), "weapons": [], "attributes": [], "watchlists": [], "notifications": [], "summary": {}}
        self.ready = False; self.allow_close = False; self.selected_listing = None
        self.market_expression = None; self.market_offset = 0; self.market_rows = []
        self.preferences = None; self.chart_dirty = False
        self.setWindowTitle("RivenScope — Riven Market Intelligence")
        self.setWindowIcon(QIcon(str(Path(__file__).parents[1] / "assets/rivenscope.svg")))
        self.setMinimumSize(900, 600); self.resize(1420, 900); self.setStyleSheet(STYLE)
        self.ui_state = QSettings(str(locations["config"] / "interface.ini"), QSettings.Format.IniFormat)
        self.channels = Channels(self)
        self.channels.in_app.connect(lambda title, body: self.show_notice(f"{title} — {body}"))
        self.channels.warning.connect(self.show_error)
        self.channels.highlight.connect(self.highlight_listing)
        root = QWidget(); self.setCentralWidget(root); layout = QHBoxLayout(root); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)
        sidebar = QFrame(); sidebar.setObjectName("sidebar"); sidebar.setFixedWidth(210)
        side = QVBoxLayout(sidebar); side.setContentsMargins(8,25,8,16)
        brand = label("◈  RivenScope", "brand"); side.addWidget(brand)
        side.addWidget(label("    MARKET INTELLIGENCE", "subtitle")); side.addSpacing(24)
        self.nav = QListWidget(); self.nav.setObjectName("navigation")
        self.nav.addItems(["Dashboard", "Market Monitor", "Watchlists", "Analytics", "Notifications", "Settings"])
        side.addWidget(self.nav)
        side.addWidget(label("PC · Crossplay requested\nEnglish · Local data only", "subtitle", True))
        side.addWidget(label(f"v{__version__}  /  Balanced", "subtitle"))
        layout.addWidget(sidebar)
        self.stack = QStackedWidget(); layout.addWidget(self.stack, 1)
        self.make_dashboard(); self.make_market(); self.make_watchlists(); self.make_analytics(); self.make_notifications(); self.make_settings()
        self.nav.currentRowChanged.connect(self.select_page); self.nav.setCurrentRow(0)
        self.statusBar().showMessage("Opening local database…")
        controller.ready.connect(self.bootstrap); controller.updated.connect(self.refresh_data)
        controller.error.connect(self.show_error); controller.scheduler_changed.connect(self.scheduler_update)
        controller.notification.connect(self.channels.deliver)
        controller.observations_changed.connect(self.load_market)
        controller.stopped.connect(self.closed_worker)
        geometry = self.ui_state.value("geometry")
        if geometry: self.restoreGeometry(geometry)
        for name in ("catalog", "market", "watchlist", "notification"):
            state = self.ui_state.value("market_header_v2" if name=="market" else name + "_header")
            if state: getattr(self, name + "_table").view.horizontalHeader().restoreState(state)
        for splitter, name in ((self.market_splitter, "market_splitter"),):
            state = self.ui_state.value(name)
            if state: splitter.restoreState(state)
        try:
            expression = json.loads(self.ui_state.value("market_filter", "null"))
            if expression: validate(expression); self.market_expression = expression
        except (ValueError, TypeError): pass

    def make_dashboard(self):
        widget, layout = page("Market overview", "Your local research workspace. Source capabilities are shown explicitly.")
        self.stack.addWidget(widget)
        self.banner = label(CONTRACT_LIMITATION, "banner", True); layout.addWidget(self.banner)
        actions = QHBoxLayout()
        self.start_button = button("Start monitoring", self.start, True); self.start_button.setEnabled(False)
        self.stop_button = button("Stop", self.controller.stop); self.stop_button.setEnabled(False)
        actions.addWidget(self.start_button); actions.addWidget(self.stop_button)
        actions.addStretch(); actions.addWidget(button("API documentation ↗", lambda: QDesktopServices.openUrl(QUrl("https://docs.warframe.market/docs/api/manifests/"))))
        layout.addLayout(actions)
        grid = QGridLayout(); grid.setSpacing(14); layout.addLayout(grid)
        self.metrics = {}
        cards = [("weapons", "Weapon catalog", "Real WFM manifest records"), ("watchlists", "Active watchlists", "Partial searches when legacy mode is enabled"),
                 ("listings", "Observed contracts", "Retained observations; total market unknown"), ("new", "New discoveries", "First-seen events since baseline"),
                 ("deals", "Potential deals", "Requires sufficient comparable data"), ("budget", "Request budget", "Shared cap: 10 requests / minute")]
        for i,(key,title,detail) in enumerate(cards):
            metric = Metric(title, "0" if key not in ("deals", "budget") else "—", detail); self.metrics[key] = metric
            grid.addWidget(metric, i//3, i%3)
        group = QGroupBox("Source & scheduler"); form = QVBoxLayout(group); layout.addWidget(group)
        self.scheduler_label = label("Stopped", wrap=True); form.addWidget(self.scheduler_label)
        self.last_update = label("Last catalog update: Never\nLast market update: Never", "subtitle", True); form.addWidget(self.last_update)
        self.coverage = label("Coverage: no recorded searches. Total market size unknown.", "subtitle", True)
        form.addWidget(self.coverage)
        self.notice = label("", "notice", True); layout.addWidget(self.notice)
        layout.addStretch()

    def make_market(self):
        widget, layout = page("Market monitor", "Browse the live weapon catalog and your own retained observations.")
        self.stack.addWidget(widget)
        self.market_tabs = QTabWidget(); layout.addWidget(self.market_tabs)
        catalog = QWidget(); cat_layout = QVBoxLayout(catalog)
        self.catalog_table = Table([("WEAPON", lambda w:w.get("i18n",{}).get("en",{}).get("name",w["slug"])),
            ("TYPE", lambda w:w.get("rivenType")), ("GROUP", lambda w:w.get("group")),
            ("DISPOSITION", lambda w:w.get("disposition")), ("BASE WEAPON MR", lambda w:w.get("reqMasteryRank"))])
        for column,width in enumerate((220,130,130,150,160)): self.catalog_table.view.setColumnWidth(column,width)
        cat_layout.addWidget(label("Official metadata, not listings. Base weapon mastery is not a rolled Riven's requirement.", "subtitle", True))
        cat_splitter = QSplitter(); cat_splitter.addWidget(self.catalog_table)
        self.catalog_details = QTextBrowser(); self.catalog_details.setOpenExternalLinks(False)
        self.catalog_details.setPlainText("Select a weapon to see applicable Riven attributes and the source metadata.")
        cat_splitter.addWidget(self.catalog_details); cat_splitter.setSizes([750,350]); cat_layout.addWidget(cat_splitter,1)
        self.catalog_table.selected.connect(self.catalog_selected)
        self.market_tabs.addTab(catalog, "Weapon catalog")
        market = QWidget(); ml = QVBoxLayout(market)
        ml.addWidget(label(CONTRACT_LIMITATION + " Existing local observations, if any, remain accessible.", "banner", True))
        filters = QHBoxLayout(); self.preset_filter = QComboBox(); self.preset_filter.addItem("All local observations", None)
        self.preset_filter.currentIndexChanged.connect(self.apply_preset)
        filters.addWidget(self.preset_filter); filters.addWidget(button("Advanced filter…", self.edit_market_filter)); filters.addWidget(button("Clear filters", self.clear_market_filter))
        filters.addStretch(); filters.addWidget(button("CSV", lambda:self.export("csv"))); filters.addWidget(button("JSON", lambda:self.export("listings"))); ml.addLayout(filters)
        columns = [("WEAPON", lambda r:r["listing"].weapon.replace("_"," ").title()),
            ("ATTRIBUTES", lambda r:" · ".join(f"{'+' if a.positive else '−'} {a.slug}: {a.value:g}" for a in r["listing"].attributes)),
            ("PRICE / BUYOUT", lambda r:r["listing"].acquisition),
            ("STARTING BID", lambda r:r["listing"].starting_bid), ("HIGHEST BID", lambda r:r["listing"].highest_bid),
            ("EST. VALUE", lambda r:r["estimate"].value),
            ("POTENTIAL PROFIT", lambda r:r["estimate"].profit), ("DISCOUNT %", lambda r:r["estimate"].discount),
            ("CONFIDENCE %", lambda r:r["estimate"].confidence if r["estimate"].value else None),
            ("SELLER STATUS", lambda r:r["listing"].seller_status), ("TYPE", lambda r:r["listing"].kind),
            ("PUBLISHED AGE", lambda r:age(r["listing"].published_at)), ("LAST SEEN", lambda r:timestamp(r["last_seen"]))]
        self.market_table = Table(columns); self.market_table.selected.connect(self.listing_selected)
        for column,width in enumerate((100,250,120,110,110)):
            self.market_table.view.setColumnWidth(column,width)
        self.market_splitter = QSplitter(); self.market_splitter.addWidget(self.market_table)
        details = QWidget(); dl = QVBoxLayout(details)
        dl.addWidget(label("Riven details", "pageTitle")); self.details = QTextBrowser(); dl.addWidget(self.details)
        self.details.setPlainText("Select an observed Riven. Auctions without buyout have no confirmed acquisition price. Raw roll context is unverified; valuation may be unavailable.")
        self.trade_buttons = []
        for text, callback in (("Open on Warframe Market ↗", self.open_listing), ("Copy seller name", self.copy_seller), ("Copy listing URL", self.copy_url), ("Copy trade message", self.copy_message)):
            b = button(text, callback); b.setEnabled(False); dl.addWidget(b); self.trade_buttons.append(b)
        self.trade_buttons[-1].setToolTip("Unavailable: current contract message format has not been verified. Use the website's copy message.")
        self.market_splitter.addWidget(details); self.market_splitter.setSizes([850,360]); ml.addWidget(self.market_splitter)
        pager = QHBoxLayout(); pager.addWidget(button("Previous page", lambda:self.market_page(-1))); pager.addWidget(button("Next page", lambda:self.market_page(1)))
        self.market_count = label("0 observations · 10,000-row pages · starting bids are not acquisition prices", "subtitle", True); pager.addWidget(self.market_count); ml.addLayout(pager)
        self.market_tabs.addTab(market, "Contracts · legacy")

    def make_watchlists(self):
        widget, layout = page("Watchlists", "Saved search logic, monitoring priorities and independent alert preferences.")
        self.stack.addWidget(widget)
        layout.addWidget(label("Enable experimental legacy searches in Settings to poll enabled presets. Responses are partial; missing rows do not prove removal.", "banner", True))
        actions = QHBoxLayout()
        for text, cb in (("+ New watchlist",self.new_watchlist), ("Edit",self.edit_watchlist), ("Duplicate",self.copy_watchlist), ("Enable / disable",self.toggle_watchlist), ("Delete",self.delete_watchlist), ("Import",lambda:self.import_data("watchlists")), ("Export",lambda:self.export("watchlists"))):
            actions.addWidget(button(text,cb,text.startswith("+")))
        layout.addLayout(actions)
        self.watchlist_table = Table([("NAME",lambda w:w["name"]), ("ENABLED",lambda w:w["enabled"]), ("PRIORITY",lambda w:w["priority"]),
            ("WEAPONS",lambda w:", ".join(w["weapons"]) or "All"), ("TYPE",lambda w:w["category"] or "All"),
            ("FILTER",lambda w:json.dumps(w["filter"])), ("SOURCE",lambda w:"Legacy partial search (opt-in)")])
        self.selected_watchlist = None
        self.watchlist_table.selected.connect(lambda value:setattr(self,"selected_watchlist",value))
        layout.addWidget(self.watchlist_table)

    def make_analytics(self):
        widget, layout = page("Analytics", "Local observations only. Asking prices, bids and transactions remain distinct.")
        self.stack.addWidget(widget)
        controls = QHBoxLayout(); self.analytics_weapon = QComboBox(); self.analytics_weapon.addItem("All observed weapons", "")
        self.analytics_weapon.currentIndexChanged.connect(self.load_analytics)
        controls.addWidget(self.analytics_weapon); controls.addWidget(button("Refresh charts",self.load_analytics)); controls.addStretch(); layout.addLayout(controls)
        self.analytics_summary = label("No observations. Price history cannot be retrieved from the documented API.","banner",True); layout.addWidget(self.analytics_summary)
        grid = QGridLayout(); layout.addLayout(grid,1)
        self.charts = {}
        for i,(key,title) in enumerate((("asking","Asking-price observations"),("distribution","Current asking-price distribution"),("bids","Auction bids · separate series"),("counts","Search result counts · partial coverage"))):
            chart=Chart(title,bars=key=="distribution"); self.charts[key]=chart; grid.addWidget(chart,i//2,i%2)
        layout.addWidget(label("Weapon-wide distributions mix distinct rolls and are descriptive only. Fair-value estimates use compatible comparables.\nVerified transaction prices: unavailable. Disappearance never confirms a sale.","subtitle",True))

    def make_notifications(self):
        widget, layout = page("Notifications", "Persistent event history with per-watchlist thresholds and duplicate suppression.")
        self.stack.addWidget(widget)
        row=QHBoxLayout(); row.addWidget(button("Configure channels & thresholds",lambda:self.nav.setCurrentRow(5))); row.addWidget(button("Test notification channels",self.test_notification)); row.addStretch(); layout.addLayout(row)
        layout.addWidget(label("No live deal notifications can be produced without contract data. Test alerts are labelled and never stored as market events.","banner",True))
        self.notification_table = Table([("TIME",lambda n:timestamp(n["at"])),("TITLE",lambda n:n["title"]),("DETAILS",lambda n:n["body"]),("RULE",lambda n:n["watchlist_id"])])
        layout.addWidget(self.notification_table)

    def make_settings(self):
        widget, layout = page("Settings & data", "Local configuration, safe backups and transparent diagnostics.")
        self.stack.addWidget(widget)
        tabs=QTabWidget(); layout.addWidget(tabs)
        self.preferences_host=QWidget(); self.preferences_layout=QVBoxLayout(self.preferences_host)
        tabs.addTab(self.preferences_host,"Preferences")
        data=QWidget(); dl=QVBoxLayout(data); tabs.addTab(data,"Data & backup")
        self.paths_label=label("Opening storage…","subtitle",True); dl.addWidget(self.paths_label)
        for text,callback in (("Back up database…",self.backup),("Restore database…",self.restore),("Export settings…",lambda:self.export("settings")),("Import settings…",lambda:self.import_data("settings")),("Export watchlists…",lambda:self.export("watchlists")),("Import watchlists…",lambda:self.import_data("watchlists")),("Prune old snapshots…",self.prune)):
            dl.addWidget(button(text,callback))
        dl.addWidget(label("Restore requires confirmation and preserves the current database in a timestamped backup. Imports validate version and format. Watchlist imports create copies.","subtitle",True)); dl.addStretch()
        diagnostic=QWidget(); diag=QVBoxLayout(diagnostic); tabs.addTab(diagnostic,"Diagnostics & updates")
        diag.addWidget(label(f"RivenScope {__version__}\nNative Qt / Wayland · SQLite · no telemetry\nContract API: experimental legacy v1 (opt-in)\nUpdate source: not configured\nUpdate method: rebuild and run the local installer; user data is retained.","subtitle",True))
        self.diagnostics=QTextBrowser(); diag.addWidget(self.diagnostics)
        diag.addWidget(button("Open local log directory",lambda:QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.locations["state"])))))
        diag.addWidget(button("Open Warframe Market rules ↗",lambda:QDesktopServices.openUrl(QUrl("https://docs.warframe.market/docs/rules/overview/"))))

    def bootstrap(self, data):
        self.ready=True; self.refresh_data(data); self.install_preferences()
        self.start_button.setEnabled(True); self.controller.scheduler.report()
        self.load_market(); self.initialized.emit()

    def refresh_data(self, data):
        self.data=data; summary=data["summary"]
        self.controller.priority=data["settings"]["global_priority"]
        self.catalog_table.model.set_rows(data["weapons"])
        self.watchlist_table.model.set_rows(data["watchlists"]); self.selected_watchlist=None
        self.notification_table.model.set_rows(data["notifications"])
        self.metrics["weapons"].value.setText(str(len(data["weapons"])))
        self.metrics["watchlists"].value.setText(str(sum(w["enabled"] for w in data["watchlists"])))
        self.metrics["listings"].value.setText(str(summary["listings"])); self.metrics["new"].value.setText(str(summary["new"]))
        mode = "enabled" if data["settings"]["legacy_contracts"] else "disabled"
        searched = summary.get("searched_weapons",0)
        self.banner.setText(f"Legacy searches {mode}. {CONTRACT_LIMITATION}")
        self.coverage.setText(f"Recorded weapon searches: {searched}/{len(data['weapons'])} catalog entries · {summary['listings']} retained contracts\nResponses are partial; total market size and pagination are unknown. Unchecked weapons: {max(0,len(data['weapons'])-searched)}.\nAt 10 requests/minute a full catalog pass can take over {len(data['weapons'])/10:.0f} minutes. Search timestamps do not prove current listing availability.")
        self.last_update.setText(f"Last catalog update: {timestamp(summary['catalog_time'])}\nLast market update: {timestamp(summary['last_market_update'])}")
        self.paths_label.setText(f"Database: {data['database']}\nLogs: {self.locations['state']}\nInterface state: {self.locations['config']}\nSchema: 2 · Snapshots: {summary['snapshots']} · Retained notifications: {summary['notifications']}")
        self.diagnostics.setPlainText("Requests (most recent first)\n"+"\n".join(f"{timestamp(r['at'])}  {r['route']}  HTTP {r['status']}  {r['message']}" for r in summary["requests"]))
        current=self.preset_filter.currentData(); self.preset_filter.blockSignals(True); self.preset_filter.clear(); self.preset_filter.addItem("All local observations",None)
        for value in data["watchlists"]: self.preset_filter.addItem(value["name"],value["id"])
        self.preset_filter.setCurrentIndex(max(0,self.preset_filter.findData(current))); self.preset_filter.blockSignals(False)
        current=self.analytics_weapon.currentData(); self.analytics_weapon.blockSignals(True); self.analytics_weapon.clear(); self.analytics_weapon.addItem("All observed weapons","")
        for weapon in data["weapons"]: self.analytics_weapon.addItem(weapon.get("i18n",{}).get("en",{}).get("name",weapon["slug"]),weapon["slug"])
        self.analytics_weapon.setCurrentIndex(max(0,self.analytics_weapon.findData(current))); self.analytics_weapon.blockSignals(False)
        dense=data["settings"]["dense_table"]
        for table in (self.catalog_table,self.market_table,self.watchlist_table,self.notification_table): table.view.verticalHeader().setDefaultSectionSize(30 if dense else 42)

    def install_preferences(self):
        while self.preferences_layout.count():
            item=self.preferences_layout.takeAt(0)
            if item.widget(): item.widget().deleteLater()
        self.preferences=Preferences(self.data["settings"])
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setWidget(self.preferences); self.preferences_layout.addWidget(scroll)
        self.preferences_layout.addWidget(button("Save preferences",self.save_preferences,True))

    def save_preferences(self):
        try: value=self.preferences.values()
        except ValueError as error: self.show_error(str(error)); return
        self.controller.submit("settings",value,lambda data:(self.refresh_data(data),self.show_notice("Preferences saved.")))

    def scheduler_update(self, value):
        self.start_button.setEnabled(self.ready and not value["running"])
        self.start_button.setText("Monitoring active" if value["running"] else "Start monitoring")
        self.stop_button.setEnabled(value["running"])
        self.metrics["budget"].value.setText(f"{value['remaining']} / 10")
        text=f"{'Monitoring active' if value['running'] else 'Stopped'} · {value['status']}\nActual HTTP starts in last minute: {value['requests_minute']} · Queue: {value['queued']} · Next allowed request in {value['wait']:.0f}s"
        self.scheduler_label.setText(text); self.statusBar().showMessage(value["status"])

    def start(self):
        if self.ready: self.controller.start()

    def select_page(self,index):
        self.stack.setCurrentIndex(index)
        if self.ready and index==3: self.load_analytics()

    def catalog_selected(self,weapon):
        applicable=[a for a in self.data["attributes"] if not a.get("exclusiveTo") or weapon.get("rivenType") in a["exclusiveTo"]]
        name=weapon.get("i18n",{}).get("en",{}).get("name",weapon["slug"])
        text=f"{name}\n\nWeapon slug: {weapon['slug']}\nType: {weapon.get('rivenType','Unknown')}\nGroup: {weapon.get('group','Unknown')}\nDisposition: {weapon.get('disposition','Unknown')}\nBase weapon MR: {weapon.get('reqMasteryRank','Unknown')}\n\nSource: Warframe Market v2 weapon manifest\n\nApplicable attributes ({len(applicable)})\n"
        for a in applicable:
            flags=[f for f in ("positiveOnly","negativeOnly","positiveIsNegative") if a.get(f)]
            text+=f"\n• {a.get('i18n',{}).get('en',{}).get('name',a['slug'])}  {a.get('unit','')}  {' / '.join(flags)}"
        text+="\n\nRolled Riven values, contract prices and seller data are not present in this manifest."
        self.catalog_details.setPlainText(text)

    def apply_preset(self):
        selected=next((w for w in self.data["watchlists"] if w["id"]==self.preset_filter.currentData()),None)
        if selected:
            children=[selected["filter"]]
            if selected["weapons"]: children.append({"field":"weapon","op":"in","value":selected["weapons"]})
            if selected["category"]: children.append({"field":"category","op":"eq","value":selected["category"]})
            self.market_expression={"op":"AND","children":children}
        else: self.market_expression=None
        self.market_offset=0; self.load_market()

    def edit_market_filter(self):
        dialog=QDialog(self); dialog.setWindowTitle("Local market filter"); dialog.resize(780,550)
        layout=QVBoxLayout(dialog); builder=FilterBuilder(self.data["attributes"]); layout.addWidget(builder)
        if self.market_expression: builder.set_expression(self.market_expression)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Apply|QDialogButtonBox.StandardButton.Cancel)
        def apply():
            try:
                self.market_expression=builder.expression(); self.market_offset=0; self.load_market(); dialog.accept()
            except ValueError as error: QMessageBox.warning(dialog,"Invalid filter",str(error))
        buttons.button(QDialogButtonBox.StandardButton.Apply).clicked.connect(apply); buttons.rejected.connect(dialog.reject); layout.addWidget(buttons); dialog.exec()

    def clear_market_filter(self):
        self.market_expression=None; self.preset_filter.setCurrentIndex(0); self.market_offset=0; self.load_market()

    def load_market(self):
        if self.ready: self.controller.submit("market",{"expression":self.market_expression,"offset":self.market_offset},self.market_loaded)

    def market_loaded(self,rows):
        self.market_rows=rows; self.market_table.model.set_rows(rows)
        self.market_count.setText(f"{len(rows)} matching rows in page {self.market_offset//MARKET_PAGE_SIZE+1} · {MARKET_PAGE_SIZE} observations per page before local filtering")
        deals=sum(row["estimate"].qualifies for row in rows); self.metrics["deals"].value.setText(str(deals) if rows else "—")
        self.metrics["deals"].detail.setText("Qualifying estimates on the current page" if rows else "Insufficient data · no contract source")

    def market_page(self,delta):
        self.market_offset=max(0,self.market_offset+delta*MARKET_PAGE_SIZE); self.load_market()

    def listing_selected(self,row):
        self.selected_listing=row; item=row["listing"]; result=row["estimate"]
        text=f"{item.weapon.replace('_',' ').title()}\nContract: {item.id}\nType: {item.kind}\n"
        text+="\nAttributes\n"+"\n".join(f"{'Positive' if a.positive else 'Negative'} · {a.slug}: {a.value:g}" for a in item.attributes)
        text+=f"\n\nRank: {item.rank} · MR: {item.mastery} · Rerolls: {item.rerolls}\nPolarity: {item.polarity or 'Unknown'}\nDisposition: {item.disposition}\n\nAsk: {item.price}\nStarting bid: {item.starting_bid}\nCurrent highest bid: {item.highest_bid}\nBuyout: {item.buyout}\nFinal auction cost: uncertain\n\n{result.status}\nValue: {result.value}\nAsking-price range: {result.low} – {result.high}\nPotential gross profit: {result.profit}\nDiscount: {result.discount}%\nConfidence: {result.confidence}%\nSample: {result.sample_size}, effective: {result.effective_sample}\nFreshness: {result.freshness_hours} hours\nRisk: {result.risk}\n"
        text+="\n"+"\n".join(result.explanation)+"\n\nComparable listing IDs\n"+"\n".join(result.comparable_ids)
        text+=f"\n\nSeller: {item.seller}\nStatus: {item.seller_status} (self-reported)\nPlatform: {item.platform}\nCrossplay: {item.crossplay}\nReputation: {item.reputation}\nURL: {item.url}\n\nPublished: {timestamp(item.published_at)}\nFirst observed: {timestamp(row['first_seen'])}\nLast observed: {timestamp(row['last_seen'])}\nState: {item.status}\n"
        self.details.setPlainText(text)
        self.trade_buttons[0].setEnabled(safe_market_url(item.url)); self.trade_buttons[1].setEnabled(bool(item.seller)); self.trade_buttons[2].setEnabled(safe_market_url(item.url))
        self.trade_buttons[3].setEnabled(False)
        def history(value):
            if self.selected_listing and self.selected_listing["listing"].id==item.id:
                suffix="\nObservation history\n"+"\n".join(f"{timestamp(e['at'])} · {e['kind']}" for e in value["events"])
                self.details.setPlainText(text+suffix)
        self.controller.submit("details",item.id,history)

    def open_url(self,url):
        if safe_market_url(url): QDesktopServices.openUrl(QUrl(url))

    def open_listing(self):
        if self.selected_listing: self.open_url(self.selected_listing["listing"].url)

    def copy_seller(self):
        if self.selected_listing: QApplication.clipboard().setText(self.selected_listing["listing"].seller)

    def copy_url(self):
        if self.selected_listing and safe_market_url(self.selected_listing["listing"].url): QApplication.clipboard().setText(self.selected_listing["listing"].url)

    def copy_message(self):
        self.show_notice("Use the website's official copy message. The current contract template is unverified.")

    def new_watchlist(self): self.watchlist_dialog()
    def edit_watchlist(self):
        if self.selected_watchlist: self.watchlist_dialog(self.selected_watchlist)

    def watchlist_dialog(self,value=None):
        dialog=WatchlistDialog(self.data["weapons"],self.data["attributes"],self.data["settings"],value,self)
        if dialog.exec(): self.controller.submit("watchlist",dialog.result_value,self.refresh_data)

    def copy_watchlist(self):
        if self.selected_watchlist:
            value=deepcopy(self.selected_watchlist); value.update(id=str(uuid.uuid4()),name=(value["name"]+" copy")[:100]); self.controller.submit("watchlist",value,self.refresh_data)

    def toggle_watchlist(self):
        if self.selected_watchlist:
            value=deepcopy(self.selected_watchlist); value["enabled"]=not value["enabled"]; self.controller.submit("watchlist",value,self.refresh_data)

    def delete_watchlist(self):
        if self.selected_watchlist and self.confirm("Delete this local watchlist?",self.selected_watchlist["name"]):
            self.controller.submit("delete_watchlist",self.selected_watchlist["id"],self.refresh_data)

    def load_analytics(self):
        if self.ready: self.controller.submit("analytics",self.analytics_weapon.currentData() or "",self.analytics_loaded)

    def analytics_loaded(self,data):
        prices=data["prices"]
        self.charts["asking"].set_points([(t,p) for t,p,_ in data["asking"]],"Observation timestamp → · platinum (asking)")
        self.charts["bids"].set_points([(t,p) for t,p,_ in data["bids"]],"Observation timestamp → · platinum (bids)")
        self.charts["counts"].set_points([(r["at"],r["count"]) for r in data["observations"]],"Observation timestamp → · listings returned")
        bins=[]
        if prices:
            low,high=min(prices),max(prices); width=max(1,(high-low)/15)
            bins=[(low+(i+.5)*width,sum(low+i*width<=p<low+(i+1)*width for p in prices)) for i in range(16)]
            oldest=min((t for t,_,_ in data["asking"]),default=None)
            self.analytics_summary.setText(f"Sample: {len(prices)} fresh active asks (up to 10,000) · median {statistics.median(prices):g}p · range {low:g}–{high:g}p\nOldest loaded observation: {timestamp(oldest)} · qualified estimates in selection: {data['qualified']}\nPlots bounded to 20,000 snapshots / 2,000 rendered points. This is not a sales history.")
        else: self.analytics_summary.setText("Insufficient current data. No fresh active asks match this selection. Historical observations, if available, remain in the plots. No synthetic history is generated.")
        self.charts["distribution"].set_points(bins,"Asking price (p) → · listing count")

    def test_notification(self):
        settings=self.data["settings"]
        self.channels.deliver({"title":"RivenScope · channel test", "body":"Test notification — not a market event or trading opportunity.","settings":settings,"listing_id":""})

    def highlight_listing(self,id_):
        if not id_: return
        self.market_table.model.highlighted.add(id_); self.market_table.view.viewport().update()

    def confirm(self,title,text):
        return QMessageBox.question(self,title,text,QMessageBox.StandardButton.Yes|QMessageBox.StandardButton.No,QMessageBox.StandardButton.No)==QMessageBox.StandardButton.Yes

    def export(self,kind):
        extension="csv" if kind=="csv" else "json"
        path,_=QFileDialog.getSaveFileName(self,"Export "+kind,f"rivenscope-{kind}.{extension}",f"{extension.upper()} (*.{extension})")
        if not path: return
        # QFileDialog has already confirmed replacement, if any.
        self.controller.submit("export",{"destination":path,"kind":kind,"overwrite":True},self.show_notice)

    def import_data(self,kind):
        path,_=QFileDialog.getOpenFileName(self,"Import "+kind,"","RivenScope JSON (*.json)")
        if not path: return
        if kind=="settings" and not self.confirm("Replace settings?","Current preferences will be replaced with validated values from this file."): return
        def loaded(data):
            self.refresh_data(data)
            if kind=="settings": self.install_preferences()
            self.show_notice("Import completed; watchlist imports create new copies.")
        self.controller.submit("import",{"source":path,"kind":kind,"confirmed":kind=="settings"},loaded)

    def backup(self):
        path,_=QFileDialog.getSaveFileName(self,"Back up database",f"rivenscope-{datetime.now():%Y%m%d-%H%M%S}.sqlite","SQLite backup (*.sqlite)")
        if path: self.controller.submit("backup",{"destination":path,"overwrite":True},self.show_notice)

    def restore(self):
        path,_=QFileDialog.getOpenFileName(self,"Restore database","","SQLite backup (*.sqlite)")
        if not path or not self.confirm("Restore database?","Monitoring will stop. The current database will be preserved before replacement. Continue?"): return
        self.controller.stop()
        def restored(value):
            self.ready=True; self.refresh_data(value["refresh"]); self.install_preferences(); self.load_market(); self.start_button.setEnabled(True); self.show_notice(value["message"])
        self.controller.submit("restore",{"source":path,"confirmed":True},restored)

    def prune(self):
        days=self.data["settings"]["retention_days"]
        if self.confirm("Prune historical snapshots?",f"Remove snapshots older than {days} days, preserving the latest snapshot per listing and notification identities. Create a backup first if needed."):
            self.controller.submit("prune",{"days":days,"confirmed":True},self.show_notice)

    def show_notice(self,text):
        self.notice.setText(str(text)); self.statusBar().showMessage(str(text),15000)

    def show_error(self,text):
        self.notice.setText("Error: "+text); self.statusBar().showMessage(text)
        cursor=self.diagnostics.textCursor(); cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText("\n"+text)
        if text.startswith("initialize:"):
            self.banner.setText("Database unavailable. Original files preserved. Use Settings → Data & backup → Restore database.")
            self.nav.setCurrentRow(5)

    def closeEvent(self,event):
        if self.allow_close:
            event.accept(); return
        event.ignore()
        self.ui_state.setValue("geometry",self.saveGeometry())
        self.ui_state.setValue("market_splitter",self.market_splitter.saveState())
        self.ui_state.setValue("market_filter",json.dumps(self.market_expression))
        for name in ("catalog","market","watchlist","notification"):
            self.ui_state.setValue("market_header_v2" if name=="market" else name+"_header",getattr(self,name+"_table").view.horizontalHeader().saveState())
        self.ui_state.sync()
        self.channels.close()
        self.setEnabled(False); self.statusBar().showMessage("Stopping requests and flushing local data…")
        self.controller.shutdown()

    def closed_worker(self):
        self.allow_close=True; self.close()
