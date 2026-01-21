#!/usr/bin/env python3
"""Functional smoke tests for IWantIt (offline, stubbed services)."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import shutil
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from iwantit.config import default_config  # noqa: E402


KAGI_FIXTURE = {
    "data": [
        {
            "title": "Artist - Album (2020)",
            "url": "https://example.com/release",
            "snippet": "Release Date 2020-01-01",
        },
        {
            "title": "Another Artist - Single (2019)",
            "url": "https://example.com/single",
            "snippet": "Release Date 2019-05-02",
        },
    ]
}

PROWLARR_FIXTURE = [
    {
        "guid": "https://tracker.example/torrents?id=1&torrentid=10",
        "age": 10,
        "indexerId": 1,
        "indexer": "tracker",
        "title": "Artist - Album - 2020 - FLAC",
        "sortTitle": "artist album 2020 flac",
        "publishDate": "2020-01-02T00:00:00Z",
        "downloadUrl": "https://prowlarr.example/download?apikey=TEST",
        "infoUrl": "https://tracker.example/torrents?id=1&torrentid=10",
        "categories": [{"id": 3000, "name": "Audio", "subCategories": []}],
        "seeders": 5,
        "leechers": 1,
        "protocol": "torrent",
        "fileName": "Artist-Album-2020-FLAC.torrent",
    },
    {
        "guid": "https://tracker.example/torrents?id=2&torrentid=20",
        "age": 5,
        "indexerId": 1,
        "indexer": "tracker",
        "title": "Artist - Album - 2020 - MP3",
        "sortTitle": "artist album 2020 mp3",
        "publishDate": "2020-01-03T00:00:00Z",
        "downloadUrl": "https://prowlarr.example/download?apikey=TEST",
        "infoUrl": "https://tracker.example/torrents?id=2&torrentid=20",
        "categories": [{"id": 3000, "name": "Audio", "subCategories": []}],
        "seeders": 2,
        "leechers": 0,
        "protocol": "torrent",
        "fileName": "Artist-Album-2020-MP3.torrent",
    },
]

HTML_PAGE = """<!doctype html>
<html>
  <head>
    <meta property="og:title" content="Artist - Album" />
    <meta name="description" content="Release Date 2020-01-01" />
  </head>
  <body>
    <h1>Artist - Album</h1>
  </body>
</html>
"""


class StubHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        if parsed.path == "/kagi":
            self._write_json(KAGI_FIXTURE)
            return
        if parsed.path == "/api/v1/search":
            self._write_json(PROWLARR_FIXTURE)
            return
        if parsed.path == "/api/v1/system/status":
            self._write_json({"version": "test"})
            return
        if parsed.path == "/page":
            self._write_html(HTML_PAGE)
            return
        self.send_response(404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802 - required by BaseHTTPRequestHandler
        parsed = urlparse(self.path)
        if parsed.path == "/api/v1/search":
            self._write_json({"status": "ok"})
            return
        self.send_response(404)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003 - BaseHTTPRequestHandler signature
        return

    def _write_json(self, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=True).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _write_html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def _start_server() -> tuple[ThreadingHTTPServer, int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), StubHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def _write_config(path: Path, port: int) -> None:
    config = default_config()
    base_url = f"http://127.0.0.1:{port}"
    config["redacted"] = {}
    config["arr"] = {}
    for key in ("redacted_enrich", "redacted_comments"):
        config.get("steps", {}).pop(key, None)
    for wf in config.get("workflows", []) or []:
        steps = wf.get("steps") or []
        wf["steps"] = [step for step in steps if not str(step).startswith("redacted_")]
    config["prowlarr"]["url"] = base_url
    config["prowlarr"]["api_key"] = "TEST"
    config["prowlarr"]["search"]["request"]["url"] = f"{base_url}/api/v1/search"
    config["prowlarr"]["grab"]["request"]["url"] = f"{base_url}/api/v1/search"
    kagi_cfg = config["web_search"]["providers"]["kagi"]
    kagi_cfg["api_key"] = "TEST"
    kagi_cfg["request"]["url"] = f"{base_url}/kagi"
    kagi_cfg["response"].pop("filter", None)
    config["web_search"]["providers"] = {"kagi": kagi_cfg}
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(config, handle, sort_keys=False)


def _run_cli(
    args: list[str],
    env: dict[str, str],
    *,
    input_data: str | None = None,
    allowed_codes: set[int] | None = None,
) -> dict[str, Any]:
    cmd = [sys.executable, "-m", "iwantit.cli"] + args
    proc = subprocess.run(
        cmd,
        input=input_data,
        capture_output=True,
        text=True,
        env=env,
    )
    if allowed_codes is None:
        allowed_codes = {0}
    if proc.returncode not in allowed_codes:
        raise RuntimeError(
            f"command failed ({proc.returncode}): {' '.join(args)}\nstdout: {proc.stdout}\nstderr: {proc.stderr}"
        )
    try:
        return json.loads(proc.stdout) if proc.stdout.strip() else {}
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid JSON output for {' '.join(args)}") from exc


def _assert(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run IWantIt functional smoke tests.")
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary config directory")
    parser.add_argument("--verbose", action="store_true", help="Print extra diagnostics")
    args = parser.parse_args()

    server, port = _start_server()
    temp_dir = Path(tempfile.mkdtemp(prefix="iwantit-functional-"))
    cfg_path = temp_dir / "config.yaml"
    secrets_path = temp_dir / "secrets.yaml"
    _write_config(cfg_path, port)
    secrets_path.write_text("{}", encoding="utf-8")

    env = os.environ.copy()
    env["IWANTIT_CONFIG"] = str(cfg_path)
    env["IWANTIT_SECRETS"] = str(secrets_path)
    env["XDG_STATE_HOME"] = str(temp_dir / "state")
    env["XDG_CACHE_HOME"] = str(temp_dir / "cache")

    try:
        run1 = _run_cli(
            ["run", "--text", "Artist - Album", "--workflow", "music", "--dry-run", "--quiet"],
            env,
            allowed_codes={0, 20},
        )
        _assert(run1.get("error") is None, "text run should not error")
        decision = (run1.get("decision") or {}).get("status")
        _assert(decision in {"selected", "needs_choice"}, "text run should reach decision")
        work = run1.get("work") or {}
        _assert(work.get("media_type") == "music", "media type should resolve to music")
        _assert(bool(work.get("candidates")), "should return candidates from prowlarr")

        run2 = _run_cli(
            ["run", "--url", f"http://127.0.0.1:{port}/page", "--workflow", "music", "--dry-run", "--quiet"],
            env,
            allowed_codes={0, 20},
        )
        _assert(run2.get("error") is None, "url run should not error")
        url_meta = run2.get("url") or {}
        _assert(url_meta.get("release_year") == 2020, "release year should parse from HTML")

        chooser = _run_cli(
            ["choose", "--stdin", "--select", "0", "--emit", "json", "--quiet"],
            env,
            input_data=json.dumps(run1, ensure_ascii=True),
        )
        _assert((chooser.get("decision") or {}).get("status") in {"selected", "needs_choice"}, "chooser should run")

        batch_path = temp_dir / "batch.jsonl"
        batch_path.write_text("Artist - Album\nAnother Artist - Single\n", encoding="utf-8")
        batch = _run_cli(
            ["run", "--batch", str(batch_path), "--jobs", "2", "--workflow", "music", "--dry-run", "--quiet"],
            env,
            allowed_codes={0, 20},
        )
        summary = batch.get("summary") or {}
        _assert(summary.get("total") == 2, "batch summary should include total")

        doctor_proc = subprocess.run(
            [sys.executable, "-m", "iwantit.cli", "doctor", "--quiet"],
            capture_output=True,
            text=True,
            env=env,
        )
        _assert(doctor_proc.returncode == 0, f"doctor failed: {doctor_proc.stderr}")

        if args.verbose:
            sys.stdout.write("Functional tests passed.\n")
    finally:
        server.shutdown()
        server.server_close()
        if args.keep_temp:
            sys.stdout.write(f"Temp config at {temp_dir}\n")
        else:
            shutil.rmtree(temp_dir, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
