#!/usr/bin/env python3
"""Refresh the static market-data snapshots the tools read on a static host.

Yahoo Finance serves no CORS headers, so a browser on GitHub Pages cannot call
it directly. This script pulls every series the four tools can request and
writes them as JSON under data/, which the client slices locally.

Usage:
    python3 scripts/fetch_data.py              # everything
    python3 scripts/fetch_data.py --daily      # daily series only
    python3 scripts/fetch_data.py --intraday   # intraday series only
    python3 scripts/fetch_data.py --symbols ^GSPC BTC-USD
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")

CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)

# Daily history start. The portfolio optimiser lets the user go back to 1990.
DAILY_START = "1990-01-01"

# Union of every whitelist across the four proxy.php files.
DAILY_SYMBOLS = [
    # indices / broad market
    "^GSPC", "^NDX", "^DJI", "URTH", "VWO", "EWJ", "FXI",
    # commodities & metals
    "GC=F", "SI=F", "HG=F", "PL=F", "CL=F", "NG=F", "ZW=F", "ZC=F",
    # crypto
    "BTC-USD", "ETH-USD", "SOL-USD", "XRP-USD", "BNB-USD", "TRX-USD",
    # sector / thematic ETFs
    "QDVE.DE", "SMH", "AIQ",
    # fixed income
    "TLT", "IEF", "SHY", "AGG", "LQD", "HYG", "EMB",
    # equities
    "AMZN", "AAPL", "MSFT", "NVDA", "TSLA", "GOOG", "META", "BRK-B",
    "TCEHY", "TSM", "NFLX", "AZO", "AVGO", "JPM", "UNH", "LLY", "V", "MA",
    "WMT", "ORCL", "AMD", "MU", "ASML", "XOM", "INTC",
    "JNJ", "KO", "PG", "CAT", "HD", "CVX", "COST", "PLTR", "ARM", "ABBV",
]

# The anomaly scanner is the only tool that asks for non-daily bars.
INTRADAY_SYMBOLS = ["^GSPC", "^NDX", "BTC-USD", "GC=F"]

# interval -> days of history to request. Yahoo caps intraday windows, so these
# sit just inside the documented limits (1m: 7d, 5m-30m: 60d, 60m: 730d).
INTRADAY_WINDOWS = {
    "1m": 7,
    "5m": 58,
    "15m": 58,
    "30m": 58,
    "60m": 700,
    "1wk": 365 * 25,
    "1mo": 365 * 40,
}

MIN_POINTS = {"1m": 30, "5m": 30, "15m": 30, "30m": 30, "60m": 30,
              "1wk": 30, "1mo": 30, "1d": 50}


def slug(symbol: str) -> str:
    """Mirror of QTT.slug() in assets/js/market-data.js."""
    return re.sub(r"[^a-z0-9]+", "_", symbol.lower())


def fetch_chart(symbol: str, interval: str, period1: int, period2: int,
                attempts: int = 4) -> list[list[float]]:
    """Return [[epoch_ms, close], ...] for one symbol/interval."""
    query = urllib.parse.urlencode({
        "period1": period1,
        "period2": period2,
        "interval": interval,
        "events": "history",
    })
    url = CHART_URL.format(symbol=urllib.parse.quote(symbol, safe="")) + "?" + query

    last_error: Exception | None = None
    for attempt in range(attempts):
        if attempt:
            # Yahoo throttles aggressively; back off with jitter.
            time.sleep(min(30, 2 ** attempt) + random.uniform(0, 1.5))
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json,text/plain,*/*",
                "Accept-Language": "en-US,en;q=0.9",
            })
            with urllib.request.urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
            break
        except Exception as exc:  # noqa: BLE001 - retry on anything transient
            last_error = exc
    else:
        raise RuntimeError(f"{symbol} {interval}: {last_error}")

    result = (payload.get("chart") or {}).get("result") or []
    if not result:
        error = (payload.get("chart") or {}).get("error")
        raise RuntimeError(f"{symbol} {interval}: respuesta sin resultado ({error})")

    node = result[0]
    stamps = node.get("timestamp") or []
    indicators = node.get("indicators") or {}

    closes = None
    adj = indicators.get("adjclose") or []
    if adj and adj[0].get("adjclose"):
        closes = adj[0]["adjclose"]
    else:
        quote = indicators.get("quote") or []
        if quote and quote[0].get("close"):
            closes = quote[0]["close"]

    if not closes:
        raise RuntimeError(f"{symbol} {interval}: sin serie de cierres")

    prices: list[list[float]] = []
    for index, stamp in enumerate(stamps):
        if index >= len(closes):
            break
        close = closes[index]
        if close is None:
            continue
        prices.append([int(stamp) * 1000, round(float(close), 6)])

    return prices


def write_snapshot(path: str, symbol: str, interval: str,
                   prices: list[list[float]]) -> dict:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    body = {
        "symbol": symbol,
        "interval": interval,
        "updated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "points": len(prices),
        "prices": prices,
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(body, handle, separators=(",", ":"))
    return {
        "interval": interval,
        "points": len(prices),
        "from": datetime.fromtimestamp(prices[0][0] / 1000, timezone.utc).strftime("%Y-%m-%d"),
        "to": datetime.fromtimestamp(prices[-1][0] / 1000, timezone.utc).strftime("%Y-%m-%d"),
    }


def load_manifest() -> dict:
    path = os.path.join(DATA, "manifest.json")
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, ValueError):
            pass
    return {"series": {}}


def save_manifest(manifest: dict) -> None:
    manifest["updated"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    os.makedirs(DATA, exist_ok=True)
    with open(os.path.join(DATA, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=1, sort_keys=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily", action="store_true", help="only daily series")
    parser.add_argument("--intraday", action="store_true", help="only intraday series")
    parser.add_argument("--symbols", nargs="*", help="restrict to these tickers")
    parser.add_argument("--pause", type=float, default=1.2,
                        help="seconds between requests (default 1.2)")
    args = parser.parse_args()

    do_daily = args.daily or not args.intraday
    do_intraday = args.intraday or not args.daily

    manifest = load_manifest()
    manifest.setdefault("series", {})

    now = datetime.now(timezone.utc)
    period2 = int(now.timestamp())

    jobs: list[tuple[str, str, int, str]] = []

    if do_daily:
        start = int(datetime.strptime(DAILY_START, "%Y-%m-%d")
                    .replace(tzinfo=timezone.utc).timestamp())
        for symbol in DAILY_SYMBOLS:
            jobs.append((symbol, "1d", start, os.path.join(DATA, "daily", slug(symbol) + ".json")))

    if do_intraday:
        for interval, days in INTRADAY_WINDOWS.items():
            start = int((now - timedelta(days=days)).timestamp())
            for symbol in INTRADAY_SYMBOLS:
                name = f"{slug(symbol)}_{interval}.json"
                jobs.append((symbol, interval, start, os.path.join(DATA, "intraday", name)))

    if args.symbols:
        wanted = set(args.symbols)
        jobs = [job for job in jobs if job[0] in wanted]

    failures: list[str] = []
    for index, (symbol, interval, period1, path) in enumerate(jobs, start=1):
        label = f"[{index}/{len(jobs)}] {symbol} {interval}"
        try:
            prices = fetch_chart(symbol, interval, period1, period2)
            if len(prices) < MIN_POINTS.get(interval, 30):
                raise RuntimeError(f"solo {len(prices)} puntos")
            entry = write_snapshot(path, symbol, interval, prices)
            manifest["series"].setdefault(symbol, {})[interval] = entry
            print(f"{label}: {entry['points']} puntos {entry['from']} → {entry['to']}", flush=True)
        except Exception as exc:  # noqa: BLE001 - one bad ticker must not stop the run
            failures.append(f"{symbol} {interval}: {exc}")
            print(f"{label}: FALLO — {exc}", file=sys.stderr, flush=True)
        time.sleep(args.pause)

    save_manifest(manifest)

    print(f"\nListo: {len(jobs) - len(failures)}/{len(jobs)} series escritas.")
    if failures:
        print(f"{len(failures)} fallos:", file=sys.stderr)
        for failure in failures:
            print("  - " + failure, file=sys.stderr)

    # A handful of dead tickers is normal (delistings, Yahoo hiccups); only a
    # wholesale failure should fail the workflow.
    return 1 if len(failures) > len(jobs) / 2 else 0


if __name__ == "__main__":
    sys.exit(main())
