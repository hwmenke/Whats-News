/**
 * data_manager.js — Data Manager tab logic
 *
 * Responsibilities:
 *  - Fetch and render the ticker library from /api/data-manager/ticker-lists
 *  - Category chip toggles + per-ticker chip selection
 *  - Search filter
 *  - SSE streaming batch fetch via /api/data-manager/fetch-batch
 *  - Progress bar + per-ticker log entries
 *  - Abort in-flight fetch
 */

// ── State ──────────────────────────────────────────────────────────────────

let _dmLibrary    = [];          // [{id, label, tickers:[]}]
let _dmSelected   = new Set();   // set of ticker strings currently checked
let _dmExpanded   = new Set();   // category ids that are expanded
let _dmReader     = null;        // ReadableStreamReader for abort
let _dmRunning    = false;
let _universeReader = null;
let _universeRunning = false;
let _universeIndices = new Set(["sp500", "sp400", "sp600", "ndx100", "russell2000"]);

// ── Init ────────────────────────────────────────────────────────────────────

async function initDataManager() {
    _dmInitUniverseSection();
    await _dmLoadDbStats();

    if (_dmLibrary.length > 0) return;   // ticker library already loaded

    try {
        const res = await fetch("/api/data-manager/ticker-lists");
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        _dmLibrary = await res.json();
        _dmRenderCategories();
    } catch (err) {
        document.getElementById("dm-categories").innerHTML =
            `<div class="dm-error">Failed to load ticker library: ${err.message}</div>`;
    }
}

// ── Universe archive (S&P / Nasdaq / Russell) ─────────────────────────────

async function _dmLoadDbStats() {
    const el = document.getElementById("universe-stats");
    if (!el) return;
    try {
        const stats = await apiFetch(`${API}/db/stats`);
        const withData = await apiFetch(`${API}/symbols/with-data?min_bars=30`);
        el.innerHTML = `
            <span>${stats.symbol_count ?? 0} registered</span>
            <span>${withData.count ?? 0} with ≥30d bars</span>
            <span>${((stats.size_bytes || 0) / 1e6).toFixed(1)} MB`;
    } catch (err) {
        el.textContent = "Stats unavailable";
    }
}

function _dmInitUniverseSection() {
    const wrap = document.getElementById("universe-indices");
    if (!wrap || wrap.dataset.ready) return;
    wrap.dataset.ready = "1";

    apiFetch(`${API}/universe/registry`).then(data => {
        wrap.innerHTML = "";
        (data.indices || []).forEach(idx => {
            const label = document.createElement("label");
            label.className = "universe-index-chip";
            const checked = _universeIndices.has(idx.id);
            label.innerHTML = `
                <input type="checkbox" data-index="${idx.id}" ${checked ? "checked" : ""}/>
                ${idx.label}`;
            label.querySelector("input").addEventListener("change", e => {
                if (e.target.checked) _universeIndices.add(idx.id);
                else _universeIndices.delete(idx.id);
            });
            wrap.appendChild(label);
        });
    }).catch(err => {
        wrap.textContent = `Registry error: ${err.message}`;
    });

    document.getElementById("btn-universe-sync")?.addEventListener("click", dmUniverseSync);
    document.getElementById("btn-universe-archive")?.addEventListener("click", () => dmUniverseJob("archive"));
    document.getElementById("btn-universe-refresh")?.addEventListener("click", () => dmUniverseJob("refresh"));
    document.getElementById("btn-universe-abort")?.addEventListener("click", dmUniverseAbort);
    document.getElementById("btn-core50")?.addEventListener("click", dmSeedCore50);
}

async function dmSeedCore50() {
    const btn = document.getElementById("btn-core50");
    if (btn) { btn.disabled = true; btn.textContent = "Seeding…"; }
    try {
        if (typeof seedCore50 === "function") {
            await seedCore50();
        } else {
            const res = await apiFetch(`${API}/universe/core50`, { method: "POST" });
            _dmLogLine(`Core 50: ${res.count || 0} names on desk (no Yahoo download)`, "ok");
        }
        await _dmLoadDbStats();
        if (typeof loadSymbols === "function") loadSymbols().catch(() => {});
    } catch (err) {
        _dmLogLine(`Core 50 failed: ${err.message}`, "err");
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = "Seed Core 50"; }
    }
}

function _dmSelectedIndices() {
    const ids = [..._universeIndices];
    return ids.length ? ids : ["all"];
}

async function dmUniverseSync() {
    const btn = document.getElementById("btn-universe-sync");
    if (btn) { btn.disabled = true; btn.textContent = "Syncing…"; }
    try {
        const res = await apiFetch(`${API}/universe/sync`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ indices: _dmSelectedIndices() }),
        });
        const sync = res.sync || {};
        _dmLogLine(
            `Universe sync: ${res.total_unique} unique · added ${(sync.added || []).length} · skipped ${(sync.skipped || []).length}`,
            "ok"
        );
        if (res.errors && Object.keys(res.errors).length) {
            Object.entries(res.errors).forEach(([k, v]) =>
                _dmLogLine(`${k}: ${v}`, "warn"));
        }
        await _dmLoadDbStats();
        if (typeof loadSymbols === "function") loadSymbols().catch(() => {});
    } catch (err) {
        _dmLogLine(`Sync failed: ${err.message}`, "err");
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = "Sync indices"; }
    }
}

async function dmUniverseJob(mode) {
    if (_universeRunning) return;
    const endpoint = mode === "archive" ? "archive" : "refresh";
    const startDate = document.getElementById("dm-start-date")?.value || "2000-01-01";
    const delay = parseFloat(document.getElementById("dm-delay")?.value || "1.5");
    const onlyMissing = document.getElementById("dm-only-missing")?.checked ?? false;
    const overlap = parseInt(document.getElementById("dm-overlap-days")?.value || "5", 10);

    const body = mode === "archive"
        ? { start_date: startDate, delay, only_missing: onlyMissing }
        : { delay: Math.min(delay, 1.5), overlap_days: overlap };

    _universeSetRunning(true);
    _dmShowProgress(true);
    _dmClearLog();
    _dmSetProgress(0, "Starting…");

    let total = 0;
    let okCount = 0;
    let failCount = 0;

    try {
        const res = await fetch(`${API}/universe/${endpoint}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body),
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
            throw new Error(err.error || `HTTP ${res.status}`);
        }

        const reader = res.body.getReader();
        _universeReader = reader;
        const dec = new TextDecoder();
        let buf = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            const parts = buf.split("\n\n");
            buf = parts.pop();

            for (const part of parts) {
                const line = part.trim();
                if (!line.startsWith("data:")) continue;
                const ev = JSON.parse(line.slice(5).trim());

                if (ev.type === "start") {
                    total = ev.total || 0;
                    _dmLogLine(`${mode} started: ${total} symbols`, "info");
                } else if (ev.type === "result") {
                    const pct = total ? Math.round(((ev.index + 1) / total) * 100) : 0;
                    _dmSetProgress(pct, `${ev.index + 1} / ${total}`);
                    if (ev.ok) {
                        okCount++;
                        if (!String(ev.msg).includes("skipped")) {
                            _dmLogLine(`✓ ${ev.symbol} — ${ev.msg}`, "ok");
                        }
                    } else {
                        failCount++;
                        _dmLogLine(`✗ ${ev.symbol} — ${ev.msg}`, "err");
                    }
                } else if (ev.type === "done") {
                    _dmSetProgress(100, `${total} / ${total}`);
                    _dmLogLine(`Done. ${ev.ok} ok, ${ev.failed} failed`, ev.failed ? "warn" : "ok");
                    _dmShowSummary(ev.ok, ev.failed);
                    await _dmLoadDbStats();
                    if (typeof loadSymbols === "function") loadSymbols().catch(() => {});
                }
            }
        }
    } catch (err) {
        if (err.name !== "AbortError") {
            _dmLogLine(`${mode} error: ${err.message}`, "err");
        }
    } finally {
        _universeReader = null;
        _universeSetRunning(false);
    }
}

function dmUniverseAbort() {
    if (_universeReader) {
        _universeReader.cancel("User aborted");
        _universeReader = null;
    }
    if (_dmReader) {
        _dmReader.cancel("User aborted");
        _dmReader = null;
    }
    _universeSetRunning(false);
    _dmSetRunning(false);
    _dmLogLine("Aborted.", "warn");
}

function _universeSetRunning(running) {
    _universeRunning = running;
    const syncBtn = document.getElementById("btn-universe-sync");
    const archBtn = document.getElementById("btn-universe-archive");
    const refBtn = document.getElementById("btn-universe-refresh");
    const abortBtn = document.getElementById("btn-universe-abort");
    if (syncBtn) syncBtn.disabled = running;
    if (archBtn) archBtn.disabled = running;
    if (refBtn) refBtn.disabled = running;
    if (abortBtn) abortBtn.style.display = running ? "" : "none";
}

// ── Render categories ───────────────────────────────────────────────────────

function _dmRenderCategories(filterText = "") {
    const container = document.getElementById("dm-categories");
    if (!container) return;

    const q = filterText.toLowerCase().trim();
    container.innerHTML = "";

    _dmLibrary.forEach(cat => {
        // Filter tickers in this category
        const tickers = q
            ? cat.tickers.filter(t => t.toLowerCase().includes(q))
            : cat.tickers;
        if (q && tickers.length === 0) return;   // hide empty categories during search

        const expanded = q || _dmExpanded.has(cat.id);
        const catSelected = tickers.length > 0 && tickers.every(t => _dmSelected.has(t));
        const catPartial  = !catSelected && tickers.some(t => _dmSelected.has(t));

        // Category header
        const header = document.createElement("div");
        header.className = "dm-cat-header";
        header.innerHTML = `
            <span class="dm-cat-toggle">${expanded ? "▾" : "▸"}</span>
            <label class="dm-cat-label">
                <input type="checkbox" class="dm-cat-check"
                       data-cat="${cat.id}"
                       ${catSelected ? "checked" : ""}
                       ${catPartial  ? "data-partial=true" : ""}/>
                ${cat.label}
                <span class="dm-cat-count">${tickers.length}</span>
            </label>`;

        header.querySelector(".dm-cat-toggle").addEventListener("click", () =>
            _dmToggleCategory(cat.id));
        header.querySelector(".dm-cat-label").addEventListener("click", e => {
            if (e.target.tagName === "INPUT") return;   // let checkbox handle itself
            _dmToggleCategory(cat.id);
        });
        header.querySelector(".dm-cat-check").addEventListener("change", e => {
            _dmSelectCategory(cat.id, e.target.checked);
        });

        // Style partial
        if (catPartial) {
            const cb = header.querySelector(".dm-cat-check");
            cb.indeterminate = true;
        }

        container.appendChild(header);

        // Ticker chips (collapsible)
        if (expanded) {
            const chips = document.createElement("div");
            chips.className = "dm-chips";
            tickers.forEach(ticker => {
                const chip = document.createElement("span");
                chip.className = "dm-chip" + (_dmSelected.has(ticker) ? " dm-chip-on" : "");
                chip.textContent = ticker;
                chip.dataset.ticker = ticker;
                chip.addEventListener("click", () => _dmToggleTicker(ticker, chip));
                chips.appendChild(chip);
            });
            container.appendChild(chips);
        }
    });

    _dmUpdateCount();
}

// ── Category / ticker toggles ────────────────────────────────────────────────

function _dmToggleCategory(catId) {
    if (_dmExpanded.has(catId)) {
        _dmExpanded.delete(catId);
    } else {
        _dmExpanded.add(catId);
    }
    const q = document.getElementById("dm-search")?.value || "";
    _dmRenderCategories(q);
}

function _dmSelectCategory(catId, checked) {
    const cat = _dmLibrary.find(c => c.id === catId);
    if (!cat) return;
    cat.tickers.forEach(t => checked ? _dmSelected.add(t) : _dmSelected.delete(t));
    const q = document.getElementById("dm-search")?.value || "";
    _dmRenderCategories(q);
}

function _dmToggleTicker(ticker, chip) {
    if (_dmSelected.has(ticker)) {
        _dmSelected.delete(ticker);
        chip.classList.remove("dm-chip-on");
    } else {
        _dmSelected.add(ticker);
        chip.classList.add("dm-chip-on");
    }
    _dmUpdateCount();
}

// ── Global select / deselect ─────────────────────────────────────────────────

function dmSelectAll() {
    _dmLibrary.forEach(cat => cat.tickers.forEach(t => _dmSelected.add(t)));
    const q = document.getElementById("dm-search")?.value || "";
    _dmRenderCategories(q);
}

function dmSelectNone() {
    _dmSelected.clear();
    const q = document.getElementById("dm-search")?.value || "";
    _dmRenderCategories(q);
}

function _dmUpdateCount() {
    const el = document.getElementById("dm-selected-count");
    if (el) el.textContent = `${_dmSelected.size} selected`;
}

// ── Search filter ────────────────────────────────────────────────────────────

function dmFilterTickers() {
    const q = document.getElementById("dm-search")?.value || "";
    _dmRenderCategories(q);
}

// ── Batch fetch ──────────────────────────────────────────────────────────────

async function dmStartBatch() {
    if (_dmRunning) return;
    const tickers = [..._dmSelected];
    if (tickers.length === 0) {
        _dmLogLine("⚠ No tickers selected.", "warn");
        return;
    }

    const startDate = document.getElementById("dm-start-date")?.value || "2000-01-01";
    const delay     = parseFloat(document.getElementById("dm-delay")?.value || "1.5");
    const addWl     = document.getElementById("dm-add-watchlist")?.checked ?? true;

    _dmSetRunning(true);
    _dmClearLog();
    _dmShowProgress(true);
    _dmSetProgress(0, `0 / ${tickers.length}`);

    const body = JSON.stringify({ tickers, start_date: startDate, delay, add_watchlist: addWl });

    let okCount   = 0;
    let failCount = 0;

    try {
        const res = await fetch("/api/data-manager/fetch-batch", {
            method:  "POST",
            headers: { "Content-Type": "application/json" },
            body,
        });

        if (!res.ok) {
            const err = await res.json().catch(() => ({ error: `HTTP ${res.status}` }));
            throw new Error(err.error || `HTTP ${res.status}`);
        }

        const reader = res.body.getReader();
        _dmReader    = reader;
        const dec    = new TextDecoder();
        let   buf    = "";

        while (true) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });

            // SSE events are separated by \n\n
            const parts = buf.split("\n\n");
            buf = parts.pop();  // keep incomplete tail

            for (const part of parts) {
                const line = part.trim();
                if (!line.startsWith("data:")) continue;
                const json = line.slice(5).trim();
                if (!json) continue;

                let ev;
                try { ev = JSON.parse(json); } catch { continue; }

                if (ev.type === "start") {
                    _dmLogLine(`Starting batch: ${ev.total} tickers.`, "info");

                } else if (ev.type === "result") {
                    const pct  = Math.round(((ev.index + 1) / tickers.length) * 100);
                    const label = `${ev.index + 1} / ${tickers.length}`;
                    _dmSetProgress(pct, label);

                    if (ev.ok) {
                        okCount++;
                        _dmLogLine(`✓ ${ev.symbol} — ${ev.msg}`, "ok");
                    } else {
                        failCount++;
                        _dmLogLine(`✗ ${ev.symbol} — ${ev.msg}`, "err");
                    }

                } else if (ev.type === "done") {
                    _dmSetProgress(100, `${tickers.length} / ${tickers.length}`);
                    _dmLogLine(
                        `Done. ${ev.ok} succeeded, ${ev.failed} failed.`,
                        ev.failed > 0 ? "warn" : "ok"
                    );
                    _dmShowSummary(ev.ok, ev.failed);
                    if (typeof loadSymbols === 'function') {
                        loadSymbols().catch(() => {});
                    }
                }
            }
        }

    } catch (err) {
        if (err.name !== "AbortError") {
            _dmLogLine(`Error: ${err.message}`, "err");
        }
    } finally {
        _dmReader = null;
        _dmSetRunning(false);
    }
}

function dmAbortBatch() {
    if (_dmReader) {
        _dmReader.cancel("User aborted");
        _dmReader = null;
    }
    _dmSetRunning(false);
    _dmLogLine("Aborted by user.", "warn");
}

// ── UI helpers ───────────────────────────────────────────────────────────────

function _dmSetRunning(running) {
    _dmRunning = running;
    const fetchBtn = document.getElementById("btn-dm-fetch");
    const abortBtn = document.getElementById("btn-dm-abort");
    if (fetchBtn) fetchBtn.style.display = running ? "none" : "";
    if (abortBtn) abortBtn.style.display = running ? "" : "none";
}

function _dmShowProgress(visible) {
    const el = document.getElementById("dm-progress-section");
    if (el) el.style.display = visible ? "" : "none";
}

function _dmSetProgress(pct, label) {
    const fill  = document.getElementById("dm-progress-fill");
    const lbl   = document.getElementById("dm-progress-label");
    const pctEl = document.getElementById("dm-progress-pct");
    if (fill)  fill.style.width = `${pct}%`;
    if (lbl)   lbl.textContent  = label;
    if (pctEl) pctEl.textContent = `${pct}%`;
}

function _dmShowSummary(ok, failed) {
    const el = document.getElementById("dm-summary");
    if (!el) return;
    el.innerHTML = `<span class="dm-sum-ok">${ok} OK</span>`
        + (failed > 0 ? ` <span class="dm-sum-err">${failed} failed</span>` : "");
}

function _dmClearLog() {
    const log = document.getElementById("dm-log");
    if (log) log.innerHTML = "";
}

function _dmLogLine(text, cls = "info") {
    const log = document.getElementById("dm-log");
    if (!log) return;
    const line = document.createElement("div");
    line.className = `dm-log-line dm-log-${cls}`;
    line.textContent = text;
    log.appendChild(line);
    log.scrollTop = log.scrollHeight;
}
