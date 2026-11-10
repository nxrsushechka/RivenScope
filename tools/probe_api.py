"""Opt-in, low-rate evidence capture. Never probes guessed/legacy routes."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import time
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
UA = "RivenScope/0.1.0 (Linux desktop; API feasibility investigation)"
URLS = {
    "versions": "https://api.warframe.market/v2/versions",
    "weapons": "https://api.warframe.market/v2/riven/weapons",
    "attributes": "https://api.warframe.market/v2/riven/attributes",
    "torid": "https://api.warframe.market/v2/riven/weapon/torid",
    "tos": "https://warframe.market/tos",
}


def main():
    directory = ROOT / "tests" / "fixtures" / "live"
    directory.mkdir(parents=True, exist_ok=True)
    evidence = []
    for name, url in URLS.items():
        row = {"url": url, "captured_at": dt.datetime.now(dt.UTC).isoformat(), "user_agent": UA}
        try:
            request = urllib.request.Request(url, headers={"User-Agent": UA, "Language": "en", "Platform": "pc", "Crossplay": "true"})
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(4 * 1024 * 1024)
                row.update(status=response.status, bytes=len(body), sha256=hashlib.sha256(body).hexdigest(), content_type=response.headers.get("Content-Type"))
                suffix = ".json" if "json" in (row["content_type"] or "") else ".html"
                (directory / (name + suffix)).write_bytes(body)
                if suffix == ".json":
                    payload = json.loads(body)
                    data = payload.get("data")
                    row.update(api_version=payload.get("apiVersion"), records=len(data) if isinstance(data, list) else 1)
        except (urllib.error.URLError, TimeoutError, ValueError) as error:
            row["error"] = str(error)
        evidence.append(row)
        print(json.dumps(row), flush=True)
        time.sleep(6.1)
    (directory / "evidence.json").write_text(json.dumps(evidence, indent=2) + "\n")


if __name__ == "__main__":
    main()
