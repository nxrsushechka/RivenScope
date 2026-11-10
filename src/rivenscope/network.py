"""Anonymous catalog requests and explicit read-only legacy auction searches."""
from dataclasses import dataclass
import json
import re
from PySide6.QtCore import QObject, QUrl, QTimer, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest
from . import __version__
from .domain import finite
from .contracts import PREFIX, search_path

ROUTES = {"versions": "/v2/versions", "weapons": "/v2/riven/weapons", "attributes": "/v2/riven/attributes"}
BASE_URL = "https://api.warframe.market"
USER_AGENT = f"RivenScope/{__version__} (Linux desktop; personal Riven research)"
MAX_BODY = 4 * 1024 * 1024


def request_path(key):
    if key in ROUTES:
        return ROUTES[key]
    if isinstance(key, str) and key.startswith(PREFIX):
        return search_path(key)
    raise ValueError("Unsupported API route")


def parse_manifest(payload, kind):
    if not isinstance(payload, dict) or payload.get("error") or "data" not in payload:
        raise ValueError("Invalid WFM response envelope")
    data = payload["data"]
    if kind == "versions":
        if not isinstance(data, dict) or not isinstance(data.get("collections"), dict) or not isinstance(data["collections"].get("rivens"), str):
            raise ValueError("Invalid version manifest")
        return data
    if kind not in ("weapons", "attributes") or not isinstance(data, list) or not 0 < len(data) <= 10000:
        raise ValueError("Invalid collection manifest")
    seen = set()
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("id"), str) or not isinstance(item.get("slug"), str) or not re.fullmatch(r"[a-z0-9_()/ -]{1,200}", item["slug"]):
            raise ValueError("Invalid manifest identity")
        if item["slug"] in seen:
            raise ValueError("Duplicate manifest slug")
        seen.add(item["slug"])
        if not 1 <= len(item["id"]) <= 200:
            raise ValueError("Invalid manifest identifier length")
        for field in ("group", "rivenType", "prefix", "suffix", "unit", "gameRef"):
            if field in item and (not isinstance(item[field], str) or len(item[field]) > 1000):
                raise ValueError("Invalid manifest text field")
        if kind == "weapons":
            finite(item.get("disposition"), "Disposition", 0)
            if type(item.get("reqMasteryRank")) is not int or not 0 <= item["reqMasteryRank"] <= 100:
                raise ValueError("Invalid weapon mastery rank")
        else:
            if "exclusiveTo" in item and (not isinstance(item["exclusiveTo"], list) or any(not isinstance(v, str) for v in item["exclusiveTo"])):
                raise ValueError("Invalid attribute restrictions")
            for flag in ("positiveOnly", "negativeOnly", "positiveIsNegative"):
                if flag in item and type(item[flag]) is not bool:
                    raise ValueError("Invalid attribute flag")
        if "i18n" in item:
            if not isinstance(item["i18n"], dict) or not isinstance(item["i18n"].get("en", {}), dict):
                raise ValueError("Invalid localization")
            name = item["i18n"].get("en", {}).get("name", "")
            if not isinstance(name, str) or len(name) > 500:
                raise ValueError("Invalid localized name")
    return data


@dataclass
class Outcome:
    key: str
    status: int
    body: bytes = b""
    retry_after: str = ""
    error: str = ""
    cancelled: bool = False


class Transport(QObject):
    finished = Signal(object)

    def __init__(self, parent=None, timeout_ms=20000):
        super().__init__(parent)
        self.manager = QNetworkAccessManager(self)
        self.reply = None
        self.buffer = bytearray()
        self.cancelled = False
        self.too_large = False
        self.key = ""
        self.timeout_ms = timeout_ms
        self.deadline = QTimer(self); self.deadline.setSingleShot(True)
        self.deadline.timeout.connect(self._timeout)
        self.timed_out = False

    def get(self, key):
        if self.reply is not None:
            raise RuntimeError("Only one API request may be active")
        path = request_path(key)
        self.key, self.buffer, self.cancelled, self.too_large = key, bytearray(), False, False
        self.timed_out = False
        request = QNetworkRequest(QUrl(BASE_URL + path))
        for name, value in {"User-Agent": USER_AGENT, "Accept": "application/json", "Language": "en", "Platform": "pc", "Crossplay": "true"}.items():
            request.setRawHeader(name.encode(), value.encode())
        request.setTransferTimeout(self.timeout_ms)
        request.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
        self.reply = self.manager.get(request)
        self.reply.readyRead.connect(self._read)
        self.reply.finished.connect(self._finished)
        self.deadline.start(self.timeout_ms + min(10000, self.timeout_ms))

    def _timeout(self):
        if self.reply is not None:
            self.timed_out = True
            self.reply.abort()

    def _read(self):
        if self.reply is None:
            return
        self.buffer.extend(bytes(self.reply.readAll()))
        if len(self.buffer) > MAX_BODY:
            self.too_large = True
            self.reply.abort()

    def _finished(self):
        reply = self.reply
        if reply is None:
            return
        self._read()
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
        error = reply.errorString() if reply.error() != reply.NetworkError.NoError else ""
        if self.too_large:
            status, error = 0, "Response exceeds 4 MB"
        if self.timed_out:
            status, error = 0, "Total request timeout"
        outcome = Outcome(self.key, status, bytes(self.buffer[:MAX_BODY]), bytes(reply.rawHeader("Retry-After")).decode("ascii", "replace"), error, self.cancelled)
        self.reply = None
        self.deadline.stop()
        self.buffer.clear()
        reply.deleteLater()
        self.finished.emit(outcome)

    def abort(self):
        if self.reply is not None:
            self.cancelled = True
            self.reply.abort()


def decode_response(outcome):
    if outcome.status != 200:
        raise ValueError(f"HTTP {outcome.status}: {outcome.error}")
    try:
        payload = json.loads(outcome.body)
    except (ValueError, UnicodeDecodeError) as error:
        raise ValueError("API did not return valid JSON") from error
    return payload if outcome.key.startswith(PREFIX) else parse_manifest(payload, outcome.key)
