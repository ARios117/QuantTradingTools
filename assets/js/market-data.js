/* ==========================================================================
   QUANT TERMINAL — market data layer
   --------------------------------------------------------------------------
   One entry point for every tool: QTT.series({ symbol, interval, from, to })
   resolving to [{ t: epochMs, y: close }, ...].

   Two sources, probed in order and remembered for the rest of the session:

     1. proxy.php  — live Yahoo Finance pull. Only exists when the site is
                     served by a PHP host.
     2. data/      — JSON snapshots committed to the repo and refreshed by
                     .github/workflows/refresh-data.yml. This is what a
                     static host (GitHub Pages) serves, since Yahoo sends no
                     CORS headers and cannot be called from the browser.

   The snapshot path is relative so the site works both at a domain root and
   under a project subpath such as /QuantTradingTools/.
   ========================================================================== */

(function (global) {
  "use strict";

  var DATA_ROOT = "../data/";
  var MANIFEST = DATA_ROOT + "manifest.json";

  var liveProxy = null;      // null = unprobed, true/false once known
  var manifestPromise = null;
  var snapshotCache = {};

  function slug(symbol) {
    return String(symbol).toLowerCase().replace(/[^a-z0-9]+/g, "_");
  }

  function toMs(value, endOfDay) {
    if (value instanceof Date) return value.getTime();
    var m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(value));
    if (!m) return NaN;
    return Date.UTC(+m[1], +m[2] - 1, +m[3], endOfDay ? 23 : 0, endOfDay ? 59 : 0, endOfDay ? 59 : 0);
  }

  function isoOf(value) {
    if (value instanceof Date) {
      var y = value.getFullYear();
      var mo = String(value.getMonth() + 1).padStart(2, "0");
      var d = String(value.getDate()).padStart(2, "0");
      return y + "-" + mo + "-" + d;
    }
    return String(value);
  }

  function fmtDay(ms) {
    return new Date(ms).toISOString().slice(0, 10);
  }

  /* ----------------------------------------------------------- tier 1 ---- */

  function fetchViaProxy(symbol, interval, fromISO, toISO) {
    var url = "proxy.php?symbol=" + encodeURIComponent(symbol) +
              "&from=" + fromISO + "&to=" + toISO + "&_=" + Date.now();
    if (interval && interval !== "1d") url += "&interval=" + encodeURIComponent(interval);

    return fetch(url, { cache: "no-store" }).then(function (res) {
      return res.text().then(function (text) {
        var json;
        try { json = JSON.parse(text); }
        catch (e) { throw new Error("__NO_PROXY__"); }
        if (!res.ok || json.error) {
          // A reachable proxy that rejects the request is still a live proxy;
          // surface its message instead of silently switching sources.
          if (res.status >= 500 || res.status === 404) throw new Error("__NO_PROXY__");
          throw new Error(json.error || ("HTTP " + res.status));
        }
        if (!Array.isArray(json.prices)) throw new Error("__NO_PROXY__");
        return json.prices;
      });
    });
  }

  /* ----------------------------------------------------------- tier 2 ---- */

  function loadManifest() {
    if (!manifestPromise) {
      manifestPromise = fetch(MANIFEST, { cache: "no-cache" })
        .then(function (res) {
          if (!res.ok) throw new Error("manifest HTTP " + res.status);
          return res.json();
        })
        .catch(function () { return { series: {} }; });
    }
    return manifestPromise;
  }

  function loadSnapshot(symbol, interval) {
    var key = interval + "/" + slug(symbol);
    if (!snapshotCache[key]) {
      var dir = interval === "1d" ? "daily" : "intraday";
      var file = interval === "1d" ? slug(symbol) : slug(symbol) + "_" + interval;
      snapshotCache[key] = fetch(DATA_ROOT + dir + "/" + file + ".json", { cache: "no-cache" })
        .then(function (res) {
          if (!res.ok) {
            throw new Error("Sin snapshot para " + symbol + " (" + interval + "). " +
                            "Añádelo a scripts/fetch_data.py y vuelve a ejecutar el workflow de datos.");
          }
          return res.json();
        });
      // A failed load must not poison the cache for later retries.
      snapshotCache[key].catch(function () { delete snapshotCache[key]; });
    }
    return snapshotCache[key];
  }

  function sliceSnapshot(snap, symbol, interval, fromMs, toMs_) {
    var all = snap.prices || [];
    if (!all.length) throw new Error("Snapshot vacío para " + symbol + ".");

    var out = [];
    for (var i = 0; i < all.length; i++) {
      var t = all[i][0];
      if (t >= fromMs && t <= toMs_) out.push(all[i]);
    }

    if (out.length < 2) {
      throw new Error(
        "El rango solicitado (" + fmtDay(fromMs) + " → " + fmtDay(toMs_) + ") queda fuera de los " +
        "datos disponibles para " + symbol + " " + interval + ", que cubren " +
        fmtDay(all[0][0]) + " → " + fmtDay(all[all.length - 1][0]) + "."
      );
    }
    return out;
  }

  function fetchViaSnapshot(symbol, interval, fromMs, toMs_) {
    return loadSnapshot(symbol, interval).then(function (snap) {
      return sliceSnapshot(snap, symbol, interval, fromMs, toMs_);
    });
  }

  /* ------------------------------------------------------- public API ---- */

  /**
   * Resolve a price series.
   * @param {object} opts
   * @param {string} opts.symbol    Yahoo ticker, e.g. "^GSPC".
   * @param {string} [opts.interval="1d"]
   * @param {string|Date} opts.from
   * @param {string|Date} opts.to
   * @returns {Promise<Array<{t:number,y:number}>>}
   */
  function series(opts) {
    var symbol = opts.symbol;
    var interval = opts.interval || "1d";
    var fromISO = isoOf(opts.from);
    var toISO = isoOf(opts.to);
    var fromMs = toMs(opts.from, false);
    var toMs_ = toMs(opts.to, true);

    if (!isFinite(fromMs) || !isFinite(toMs_) || toMs_ <= fromMs) {
      return Promise.reject(new Error("Rango de fechas inválido."));
    }

    function normalise(prices) {
      var out = [];
      for (var i = 0; i < prices.length; i++) {
        var t = +prices[i][0], y = +prices[i][1];
        if (isFinite(t) && isFinite(y)) out.push({ t: t, y: y });
      }
      out.sort(function (a, b) { return a.t - b.t; });
      if (out.length < 2) throw new Error("Serie de precios insuficiente para " + symbol + ".");
      return out;
    }

    var attempt;

    if (liveProxy === false) {
      attempt = fetchViaSnapshot(symbol, interval, fromMs, toMs_);
    } else {
      attempt = fetchViaProxy(symbol, interval, fromISO, toISO)
        .then(function (prices) {
          liveProxy = true;
          return prices;
        })
        .catch(function (err) {
          // Anything that says "there is no PHP here" demotes us to snapshots
          // permanently; a genuine proxy error propagates.
          if (err && err.message === "__NO_PROXY__" ||
              err instanceof TypeError ||
              (err && err.name === "TypeError")) {
            liveProxy = false;
            return fetchViaSnapshot(symbol, interval, fromMs, toMs_);
          }
          throw err;
        });
    }

    return attempt.then(normalise);
  }

  /** Human label for the active source, for status lines. */
  function sourceLabel() {
    if (liveProxy === true) return "Yahoo Finance · live";
    if (liveProxy === false) return "snapshot local";
    return "—";
  }

  /** Last refresh timestamp of the snapshot set, when known. */
  function snapshotDate() {
    return loadManifest().then(function (m) { return m.updated || null; });
  }

  global.QTT = {
    series: series,
    sourceLabel: sourceLabel,
    snapshotDate: snapshotDate,
    slug: slug
  };
})(window);
