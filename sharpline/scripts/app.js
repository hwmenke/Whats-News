/* SharpLine frontend — vanilla JS, no build step. */

const API = "";
let TEAMS = {};
let BOARD = null;
let EDGES = null;

const $ = (sel) => document.querySelector(sel);
const fmtOdds = (o) => (o > 0 ? `+${o}` : `${o}`);
const fmtLine = (l) => (l == null ? "—" : l > 0 ? `+${l}` : `${l}`);
const fmtPct = (p) => (p == null ? "—" : `${(p * 100).toFixed(1)}%`);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function teamColor(abbr) { return (TEAMS[abbr] || {}).color || "#888"; }
function teamName(abbr) { return (TEAMS[abbr] || {}).name || abbr; }

function fmtKick(iso) {
  const d = new Date(iso);
  return d.toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

/* ---------- Tabs ---------- */

document.querySelectorAll(".tab").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab").forEach((b) => b.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.remove("active"));
    btn.classList.add("active");
    $(`#tab-${btn.dataset.tab}`).classList.add("active");
  });
});

/* ---------- Data loading ---------- */

async function loadAll(refresh = false) {
  const q = refresh ? "?refresh=1" : "";
  const [teams, edges, settings] = await Promise.all([
    fetch(`${API}/api/teams`).then((r) => r.json()),
    fetch(`${API}/api/edges${q}`).then((r) => r.json()),
    fetch(`${API}/api/settings`).then((r) => r.json()),
  ]);
  TEAMS = teams;
  EDGES = edges;
  BOARD = await fetch(`${API}/api/board`).then((r) => r.json());

  const badge = $("#source-badge");
  badge.textContent = edges.source === "live" ? "LIVE ODDS" : "SAMPLE DATA";
  badge.className = `badge ${edges.source === "live" ? "badge-live" : "badge-sample"}`;
  $("#as-of").textContent = `as of ${new Date(edges.as_of * 1000).toLocaleTimeString()}`;
  $("#cap-label").textContent = `${(settings.max_bet_pct * 100).toFixed(1)}%`;

  renderBoard();
  renderEdges();
  renderRatings();
  renderBets();
  fillSettings(settings);
  fillBetGameOptions();
}

$("#refresh-btn").addEventListener("click", () => loadAll(true));

/* ---------- Odds board ---------- */

function bestSet(games) {
  // For each game compute the best (most bettable) value per column.
  const best = {};
  for (const g of games) {
    const b = { spreadHome: -Infinity, spreadAway: -Infinity, mlHome: -Infinity, mlAway: -Infinity };
    const dec = (o) => (o > 0 ? 1 + o / 100 : 1 + 100 / -o);
    for (const q of Object.values(g.books)) {
      if (q.spread) {
        b.spreadHome = Math.max(b.spreadHome, q.spread.home_line * 1000 + dec(q.spread.home_price));
        b.spreadAway = Math.max(b.spreadAway, -q.spread.home_line * 1000 + dec(q.spread.away_price));
      }
      if (q.moneyline) {
        b.mlHome = Math.max(b.mlHome, dec(q.moneyline.home));
        b.mlAway = Math.max(b.mlAway, dec(q.moneyline.away));
      }
    }
    best[g.id] = b;
  }
  return best;
}

function renderBoard() {
  const cont = $("#board-container");
  if (!BOARD || !BOARD.games.length) { cont.innerHTML = "<p>No games on the board.</p>"; return; }
  const best = bestSet(BOARD.games);
  const dec = (o) => (o > 0 ? 1 + o / 100 : 1 + 100 / -o);

  const analysed = Object.fromEntries((EDGES?.games || []).map((g) => [g.game_id, g]));

  cont.innerHTML = BOARD.games.map((g) => {
    const a = analysed[g.id];
    const pHome = a ? a.model.home_win_prob : 0.5;
    const b = best[g.id];

    const rows = Object.entries(g.books).map(([book, q]) => {
      const sH = q.spread, ml = q.moneyline, t = q.total;
      const isBest = (val, key) => Math.abs(val - b[key]) < 1e-9 ? " class=\"best\"" : "";
      return `<tr>
        <td>${esc(book)}</td>
        <td${sH ? isBest(sH.home_line * 1000 + dec(sH.home_price), "spreadHome") : ""}>${sH ? `${fmtLine(sH.home_line)} <span class="sub">${fmtOdds(sH.home_price)}</span>` : "—"}</td>
        <td${sH ? isBest(-sH.home_line * 1000 + dec(sH.away_price), "spreadAway") : ""}>${sH ? `${fmtLine(-sH.home_line)} <span class="sub">${fmtOdds(sH.away_price)}</span>` : "—"}</td>
        <td${ml ? isBest(dec(ml.home), "mlHome") : ""}>${ml ? fmtOdds(ml.home) : "—"}</td>
        <td${ml ? isBest(dec(ml.away), "mlAway") : ""}>${ml ? fmtOdds(ml.away) : "—"}</td>
        <td>${t ? `${t.line} <span class="sub">o${fmtOdds(t.over)} / u${fmtOdds(t.under)}</span>` : "—"}</td>
      </tr>`;
    }).join("");

    const pmRows = Object.entries(g.prediction_markets || {}).map(([mkt, q]) => `
      <tr class="pm-row">
        <td>${esc(mkt)}</td><td>—</td><td>—</td>
        <td>${fmtPct(q.home_prob)}</td><td>${fmtPct(1 - q.home_prob)}</td><td>—</td>
      </tr>`).join("");

    const consRow = a && a.consensus ? `
      <tr class="consensus-row">
        <td>Consensus (de-vig)</td>
        <td>${fmtLine(a.consensus.home_line)}</td>
        <td>${fmtLine(a.consensus.home_line == null ? null : -a.consensus.home_line)}</td>
        <td>${fmtPct(a.consensus.home_prob)}</td>
        <td>${fmtPct(a.consensus.home_prob == null ? null : 1 - a.consensus.home_prob)}</td>
        <td>${a.consensus.total ?? "—"}</td>
      </tr>
      <tr class="consensus-row">
        <td>SharpLine model</td>
        <td>${fmtLine(a.model.model_spread_home)}</td>
        <td>${fmtLine(-a.model.model_spread_home)}</td>
        <td>${fmtPct(a.model.home_win_prob)}</td>
        <td>${fmtPct(a.model.away_win_prob)}</td>
        <td>—</td>
      </tr>` : "";

    return `<div class="game-card">
      <div class="game-head">
        <div class="matchup">
          <span class="team-chip"><span class="team-dot" style="background:${teamColor(g.away)}"></span>${esc(teamName(g.away))}</span>
          <span class="at-sign">at</span>
          <span class="team-chip"><span class="team-dot" style="background:${teamColor(g.home)}"></span>${esc(teamName(g.home))}</span>
        </div>
        <div class="winprob-bar" title="Model win probability">
          <div class="winprob-seg away" style="width:${((1 - pHome) * 100).toFixed(1)}%;background:${teamColor(g.away)}">${g.away} ${((1 - pHome) * 100).toFixed(0)}%</div>
          <div class="winprob-seg home" style="width:${(pHome * 100).toFixed(1)}%;background:${teamColor(g.home)}">${g.home} ${(pHome * 100).toFixed(0)}%</div>
        </div>
        <span class="kickoff">${fmtKick(g.kickoff)}</span>
        <button class="movement-toggle" data-game="${esc(g.id)}">Line moves ▾</button>
      </div>
      <table class="odds-table">
        <thead><tr>
          <th>Source</th><th>${g.home} spread</th><th>${g.away} spread</th>
          <th>${g.home} ML</th><th>${g.away} ML</th><th>Total</th>
        </tr></thead>
        <tbody>${rows}${pmRows}${consRow}</tbody>
      </table>
      <div class="movement-box" id="move-${esc(g.id)}" style="display:none"></div>
    </div>`;
  }).join("");

  cont.querySelectorAll(".movement-toggle").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const box = $(`#move-${CSS.escape(btn.dataset.game)}`);
      if (box.style.display !== "none") { box.style.display = "none"; return; }
      box.style.display = "block";
      box.textContent = "Loading…";
      const moves = await fetch(`${API}/api/movement/${encodeURIComponent(btn.dataset.game)}`).then((r) => r.json());
      if (!moves.length) { box.textContent = "No snapshots yet — hit “Refresh odds” a few times over the week to build line-movement history."; return; }
      const byBook = {};
      for (const m of moves) (byBook[m.book] ||= []).push(m);
      box.innerHTML = Object.entries(byBook).map(([book, ms]) => {
        const path = ms.map((m) => fmtLine(m.home_line)).join(" → ");
        return `<div><b>${esc(book)}</b>: ${path}</div>`;
      }).join("");
    });
  });
}

/* ---------- Edges & picks ---------- */

function renderEdges() {
  const picks = EDGES?.picks || [];
  const pc = $("#picks-container");
  pc.innerHTML = picks.length ? picks.map((p, i) => `
    <div class="pick-card">
      <div class="pick-rank">${i + 1}</div>
      <div class="pick-main">
        <div class="pick-bet">${esc(teamName(p.team))} ${p.market === "spread" ? fmtLine(p.line) : "ML"} <span class="sub">${fmtOdds(p.price)}</span></div>
        <div class="pick-detail">${esc(p.matchup)} · ${fmtKick(p.kickoff)} · best price at <b>${esc(p.book)}</b></div>
        <div class="stars">${"★".repeat(p.stars)}${"☆".repeat(5 - p.stars)}</div>
      </div>
      <div class="pick-stats">
        <div class="pick-stat"><b>${fmtPct(p.model_prob)}</b><span class="lbl">model prob</span></div>
        <div class="pick-stat"><b class="pos">+${(p.edge * 100).toFixed(1)}%</b><span class="lbl">edge vs price</span></div>
        <div class="pick-stat"><b>${(p.ev_per_dollar * 100).toFixed(1)}¢</b><span class="lbl">EV per $1</span></div>
        <div class="pick-stat"><b>$${p.stake.toFixed(0)}</b><span class="lbl">kelly stake</span></div>
      </div>
    </div>`).join("")
    : `<div class="no-picks">No plays clear the edge threshold right now. That is the normal state of an efficient market — Walters passed on most games too.</div>`;

  const games = EDGES?.games || [];
  $("#edges-container").innerHTML = `
    <table class="flat-table">
      <thead><tr>
        <th>Game</th><th>Kickoff</th><th>Market line</th><th>Model line</th>
        <th>Line value</th><th>Mkt home win%</th><th>Model home win%</th><th>Prob gap</th>
      </tr></thead>
      <tbody>${games.map((g) => {
        const gap = g.consensus.home_prob == null ? null : g.model.home_win_prob - g.consensus.home_prob;
        const lv = g.line_value;
        return `<tr>
          <td>${g.away} @ ${g.home}</td>
          <td>${fmtKick(g.kickoff)}</td>
          <td>${fmtLine(g.consensus.home_line)}</td>
          <td>${fmtLine(g.model.model_spread_home)}</td>
          <td class="${lv > 0 ? "pos" : lv < 0 ? "neg" : ""}">${lv == null ? "—" : fmtLine(lv)}</td>
          <td>${fmtPct(g.consensus.home_prob)}</td>
          <td>${fmtPct(g.model.home_win_prob)}</td>
          <td class="${gap > 0 ? "pos" : gap < 0 ? "neg" : ""}">${gap == null ? "—" : (gap > 0 ? "+" : "") + (gap * 100).toFixed(1) + "%"}</td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
}

/* ---------- Ratings ---------- */

async function renderRatings() {
  const ratings = await fetch(`${API}/api/ratings`).then((r) => r.json());
  const max = Math.max(...ratings.map((r) => Math.abs(r.rating)), 6);
  $("#ratings-container").innerHTML = `
    <table class="flat-table">
      <thead><tr><th>#</th><th>Team</th><th>Division</th><th class="rating-bar-cell">Rating vs average</th><th>Points</th></tr></thead>
      <tbody>${ratings.map((r, i) => {
        const pct = (Math.abs(r.rating) / max) * 50;
        const left = r.rating >= 0 ? 50 : 50 - pct;
        return `<tr>
          <td>${i + 1}</td>
          <td><span class="team-dot" style="background:${r.color}"></span> ${esc(r.name)}</td>
          <td>${esc(r.div)}</td>
          <td class="rating-bar-cell">
            <div class="rating-bar-track">
              <div class="rating-bar-zero"></div>
              <div class="rating-bar-fill" style="left:${left}%;width:${pct}%;background:${r.rating >= 0 ? "var(--good)" : "var(--bad)"}"></div>
            </div>
          </td>
          <td><input class="rating-input" data-team="${r.team}" type="number" step="0.5" value="${r.rating}" /></td>
        </tr>`;
      }).join("")}</tbody>
    </table>`;
}

$("#save-ratings").addEventListener("click", async () => {
  const payload = {};
  document.querySelectorAll(".rating-input").forEach((inp) => { payload[inp.dataset.team] = parseFloat(inp.value); });
  await fetch(`${API}/api/ratings`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
  $("#ratings-status").textContent = "Saved — board repriced.";
  setTimeout(() => ($("#ratings-status").textContent = ""), 2500);
  await loadAll();
});

$("#reset-ratings").addEventListener("click", async () => {
  await fetch(`${API}/api/ratings/reset`, { method: "POST" });
  await loadAll();
});

/* ---------- Bets ---------- */

async function renderBets() {
  const data = await fetch(`${API}/api/bets`).then((r) => r.json());
  const s = data.summary;
  $("#bet-summary").innerHTML = `
    <div class="stat-card"><b>${s.record || "0-0"}</b><span>Record</span></div>
    <div class="stat-card"><b class="${s.profit >= 0 ? "pos" : "neg"}">$${s.profit.toFixed(2)}</b><span>Profit</span></div>
    <div class="stat-card"><b class="${s.roi_pct >= 0 ? "pos" : "neg"}">${s.roi_pct.toFixed(1)}%</b><span>ROI</span></div>
    <div class="stat-card"><b class="${(s.avg_clv_pct ?? 0) >= 0 ? "pos" : "neg"}">${s.avg_clv_pct == null ? "—" : s.avg_clv_pct.toFixed(2) + "%"}</b><span>Avg CLV</span></div>
    <div class="stat-card"><b>${s.n_open}</b><span>Open bets</span></div>`;

  const rows = data.bets.map((b) => `
    <tr>
      <td>${esc(b.description)}<br><span class="sub">${esc(b.book || "")}</span></td>
      <td>${esc(b.market)} / ${esc(b.side)}</td>
      <td>${fmtLine(b.line)}</td>
      <td>${fmtOdds(b.odds)}</td>
      <td>$${b.stake.toFixed(2)}</td>
      <td class="status-${b.status}">${b.status.toUpperCase()}</td>
      <td>${b.payout == null ? "—" : "$" + (b.payout - b.stake).toFixed(2)}</td>
      <td class="${(b.clv_pct ?? 0) >= 0 ? "pos" : "neg"}">${b.clv_pct == null ? "—" : b.clv_pct.toFixed(2) + "%"}</td>
      <td>
        ${b.status === "open" ? `
          <button class="btn btn-mini settle" data-id="${b.id}" data-status="won">W</button>
          <button class="btn btn-mini settle" data-id="${b.id}" data-status="lost">L</button>
          <button class="btn btn-mini settle" data-id="${b.id}" data-status="push">P</button>` : ""}
        <button class="btn btn-mini del" data-id="${b.id}">✕</button>
      </td>
    </tr>`).join("");

  $("#bets-container").innerHTML = data.bets.length ? `
    <table class="flat-table">
      <thead><tr><th>Bet</th><th>Market</th><th>Line</th><th>Odds</th><th>Stake</th><th>Status</th><th>P/L</th><th>CLV</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table>` : `<div class="no-picks">No bets logged yet.</div>`;

  $("#bets-container").querySelectorAll(".settle").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const closing = prompt("Closing odds for this bet (for CLV, e.g. -115)? Leave blank to skip:");
      const body = { status: btn.dataset.status };
      if (closing && closing.trim()) body.closing_odds = parseInt(closing, 10);
      await fetch(`${API}/api/bets/${btn.dataset.id}/settle`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      renderBets();
    });
  });
  $("#bets-container").querySelectorAll(".del").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!confirm("Delete this bet?")) return;
      await fetch(`${API}/api/bets/${btn.dataset.id}`, { method: "DELETE" });
      renderBets();
    });
  });
}

function fillBetGameOptions() {
  const sel = $("#bf-game");
  sel.innerHTML = (BOARD?.games || []).map((g) =>
    `<option value="${esc(g.id)}">${g.away} @ ${g.home} — ${fmtKick(g.kickoff)}</option>`).join("");
  const books = new Set();
  (BOARD?.games || []).forEach((g) => Object.keys(g.books).forEach((b) => books.add(b)));
  $("#book-list").innerHTML = [...books].map((b) => `<option value="${esc(b)}">`).join("");
}

$("#bet-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const gameId = $("#bf-game").value;
  const g = (BOARD?.games || []).find((x) => x.id === gameId);
  const bet = {
    game_id: gameId,
    description: g ? `${g.away} @ ${g.home}` : gameId,
    market: $("#bf-market").value,
    side: $("#bf-side").value,
    line: $("#bf-line").value === "" ? null : parseFloat($("#bf-line").value),
    odds: parseInt($("#bf-odds").value, 10),
    stake: parseFloat($("#bf-stake").value),
    book: $("#bf-book").value || null,
  };
  const resp = await fetch(`${API}/api/bets`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(bet) });
  if (resp.ok) { e.target.reset(); renderBets(); }
  else alert((await resp.json()).error || "Failed to log bet");
});

/* ---------- Settings ---------- */

function fillSettings(s) {
  $("#set-bankroll").value = s.bankroll;
  $("#set-kelly").value = s.kelly_fraction;
  $("#set-cap").value = s.max_bet_pct;
  $("#set-threshold").value = s.edge_threshold;
  $("#set-hfa").value = s.hfa;
}

$("#save-settings").addEventListener("click", async () => {
  const body = {
    bankroll: parseFloat($("#set-bankroll").value),
    kelly_fraction: parseFloat($("#set-kelly").value),
    max_bet_pct: parseFloat($("#set-cap").value),
    edge_threshold: parseFloat($("#set-threshold").value),
    hfa: parseFloat($("#set-hfa").value),
  };
  await fetch(`${API}/api/settings`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  $("#settings-status").textContent = "Saved — edges recomputed.";
  setTimeout(() => ($("#settings-status").textContent = ""), 2500);
  await loadAll();
});

/* ---------- Boot ---------- */

loadAll().catch((err) => {
  document.body.insertAdjacentHTML("afterbegin",
    `<div style="background:#fbe9e7;color:#d6443a;padding:10px 20px;font-weight:600">Failed to load data: ${esc(err.message)} — is the server running?</div>`);
});
