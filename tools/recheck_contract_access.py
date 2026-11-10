"""Read-only upstream research: capture official sources without probing contract routes.

Writes a new evidence directory, never overwrites the original API test fixtures.
Does not activate capabilities, publish messages, register accounts, or use credentials.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time
import urllib.error
import urllib.request


ROOT = Path(__file__).resolve().parents[1]
USER_AGENT = "RivenScope/0.1.0 (Linux desktop; public contract API access research)"
SOURCES = {
    "intro": "https://docs.warframe.market/docs/intro/",
    "sitemap": "https://docs.warframe.market/sitemap.xml",
    "subscriptions": "https://docs.warframe.market/docs/websockets/subscriptions/",
    "oauth": "https://docs.warframe.market/docs/oauth/overview/",
    "contributing": "https://docs.warframe.market/docs/contributing/wfm-docs/",
    "electron_example": "https://docs.warframe.market/docs/contributing/wfm-electron/",
    "tos": "https://warframe.market/tos",
    "official_docs_tree": "https://api.github.com/repos/42bytes-team/wfm-docs/git/trees/master?recursive=1",
}


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)

    def handle_data(self, text):
        if not self.skip and text.strip():
            self.parts.append(text.strip())


def extract_terms(html):
    match = re.search(r'<script[^>]*id="application-locale-messages"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        raise ValueError("Official terms JSON was not found; manual review required")
    payload = json.loads(match[1])
    terms = {}

    def visit(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if key.startswith("app.tos.") and isinstance(child, str):
                    terms[key] = child
                if isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(value, list):
            for child in value:
                visit(child)

    visit(payload)
    if not terms.get("app.tos.api.rateLimit"):
        raise ValueError("API terms are missing; manual review required")
    return terms


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    output = args.output or ROOT / "docs/evidence" / (stamp + "-contract-access")
    output.mkdir(parents=True, exist_ok=False)
    evidence, last_start = [], 0.0
    for name, url in SOURCES.items():
        delay = 6.1 - (time.monotonic() - last_start)
        if delay > 0:
            time.sleep(delay)
        last_start = time.monotonic()
        row = {"source": name, "url": url, "captured_at": datetime.now(timezone.utc).isoformat(),
               "user_agent": USER_AGENT}
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "*/*"})
            with urllib.request.urlopen(request, timeout=30) as response:
                body = response.read(4 * 1024 * 1024 + 1)
                if len(body) > 4 * 1024 * 1024:
                    raise ValueError("Research response exceeds 4 MiB")
                text = body.decode("utf-8")
                suffix = ".json" if name == "official_docs_tree" else ".xml" if name == "sitemap" else ".html"
                file = name + suffix
                (output / file).write_bytes(body)
                row.update(status=response.status, file=file, bytes=len(body), sha256=hashlib.sha256(body).hexdigest())
                if name == "tos":
                    (output / "tos-extracted.json").write_text(json.dumps(extract_terms(text), indent=2) + "\n")
                elif name == "official_docs_tree":
                    payload = json.loads(text)
                    if payload.get("truncated"):
                        raise ValueError("Repository tree is truncated; review cannot establish completeness")
                    row["tree_sha"] = payload["sha"]
                    row["api_doc_paths"] = [item["path"] for item in payload["tree"] if item["path"].startswith("docs/api/")]
                elif suffix == ".html":
                    parsed = Text()
                    parsed.feed(text)
                    (output / (name + ".txt")).write_text("\n".join(parsed.parts) + "\n")
        except urllib.error.HTTPError as error:
            row.update(status=error.code, error=str(error), retry_after=error.headers.get("Retry-After"))
        except (urllib.error.URLError, ValueError, TimeoutError) as error:
            row["error"] = str(error)
        evidence.append(row)
        print(json.dumps(row), flush=True)
        if row.get("status") in (401, 403, 429, 509):
            break  # Respect access restrictions/rate limiting; no retries or bypass.
    manifest = {"purpose": "Official source review; not proof that contract access exists or does not exist",
                "sources": evidence, "automatic_capability_activation": False}
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print("Evidence directory:", output)
    return 0 if len(evidence) == len(SOURCES) and all(not r.get("error") for r in evidence) else 1


if __name__ == "__main__":
    raise SystemExit(main())
