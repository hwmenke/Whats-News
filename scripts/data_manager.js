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

// ── Init ────────────────────────────────────────────────────────────────────

async function initDataManager() {
    if (_dmLibrary.length > 0) return;   // already loaded

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
