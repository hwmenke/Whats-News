// pro-markets-data.jsx — stock universe + deterministic performance model
// for the Markets (heatmap + screener) view. All figures illustrative.

const SCR_STOCKS = [
  // Technology
  { sym: 'NVDA', name: 'Nvidia', sector: 'Technology', mcap: 3510, px: 142.80, pe: 71.2, yld: 0.0 },
  { sym: 'AAPL', name: 'Apple', sector: 'Technology', mcap: 3320, px: 218.50, pe: 32.4, yld: 0.5 },
  { sym: 'MSFT', name: 'Microsoft', sector: 'Technology', mcap: 3280, px: 442.10, pe: 36.1, yld: 0.7 },
  { sym: 'AVGO', name: 'Broadcom', sector: 'Technology', mcap: 830, px: 178.40, pe: 39.2, yld: 1.2 },
  { sym: 'ORCL', name: 'Oracle', sector: 'Technology', mcap: 390, px: 141.20, pe: 38.0, yld: 1.1 },
  { sym: 'CRM', name: 'Salesforce', sector: 'Technology', mcap: 275, px: 286.00, pe: 56.8, yld: 0.6 },
  { sym: 'AMD', name: 'AMD', sector: 'Technology', mcap: 262, px: 162.30, pe: 198.0, yld: 0.0 },
  { sym: 'ADBE', name: 'Adobe', sector: 'Technology', mcap: 240, px: 540.30, pe: 45.1, yld: 0.0 },
  { sym: 'CSCO', name: 'Cisco', sector: 'Technology', mcap: 230, px: 57.40, pe: 17.2, yld: 2.9 },
  { sym: 'IBM', name: 'IBM', sector: 'Technology', mcap: 220, px: 240.10, pe: 28.3, yld: 2.7 },
  { sym: 'QCOM', name: 'Qualcomm', sector: 'Technology', mcap: 210, px: 188.60, pe: 22.4, yld: 1.8 },
  { sym: 'TXN', name: 'Texas Instruments', sector: 'Technology', mcap: 190, px: 208.40, pe: 34.0, yld: 2.4 },
  { sym: 'NOW', name: 'ServiceNow', sector: 'Technology', mcap: 180, px: 880.20, pe: 95.4, yld: 0.0 },
  { sym: 'INTC', name: 'Intel', sector: 'Technology', mcap: 130, px: 31.20, pe: 88.0, yld: 0.0 },
  // Communications
  { sym: 'GOOGL', name: 'Alphabet', sector: 'Communications', mcap: 2170, px: 178.30, pe: 24.7, yld: 0.4 },
  { sym: 'META', name: 'Meta Platforms', sector: 'Communications', mcap: 1380, px: 542.20, pe: 28.3, yld: 0.4 },
  { sym: 'NFLX', name: 'Netflix', sector: 'Communications', mcap: 290, px: 678.40, pe: 44.0, yld: 0.0 },
  { sym: 'TMUS', name: 'T-Mobile US', sector: 'Communications', mcap: 280, px: 240.50, pe: 24.1, yld: 1.3 },
  { sym: 'DIS', name: 'Disney', sector: 'Communications', mcap: 205, px: 113.40, pe: 40.2, yld: 0.8 },
  { sym: 'VZ', name: 'Verizon', sector: 'Communications', mcap: 170, px: 41.20, pe: 9.4, yld: 6.5 },
  // Financials
  { sym: 'BRK-B', name: 'Berkshire Hathaway', sector: 'Financials', mcap: 988, px: 462.30, pe: 8.9, yld: 0.0 },
  { sym: 'JPM', name: 'JPMorgan Chase', sector: 'Financials', mcap: 618, px: 220.10, pe: 12.4, yld: 2.1 },
  { sym: 'V', name: 'Visa', sector: 'Financials', mcap: 560, px: 282.00, pe: 30.2, yld: 0.8 },
  { sym: 'MA', name: 'Mastercard', sector: 'Financials', mcap: 430, px: 462.10, pe: 36.4, yld: 0.6 },
  { sym: 'BAC', name: 'Bank of America', sector: 'Financials', mcap: 310, px: 40.10, pe: 13.0, yld: 2.4 },
  { sym: 'WFC', name: 'Wells Fargo', sector: 'Financials', mcap: 210, px: 61.40, pe: 12.2, yld: 2.3 },
  { sym: 'AXP', name: 'American Express', sector: 'Financials', mcap: 180, px: 250.30, pe: 19.4, yld: 1.2 },
  { sym: 'MS', name: 'Morgan Stanley', sector: 'Financials', mcap: 170, px: 105.20, pe: 16.1, yld: 3.2 },
  { sym: 'GS', name: 'Goldman Sachs', sector: 'Financials', mcap: 160, px: 480.60, pe: 15.0, yld: 2.3 },
  { sym: 'C', name: 'Citigroup', sector: 'Financials', mcap: 120, px: 63.10, pe: 19.0, yld: 3.4 },
  // Health Care
  { sym: 'LLY', name: 'Eli Lilly', sector: 'Health Care', mcap: 780, px: 822.10, pe: 80.1, yld: 0.5 },
  { sym: 'UNH', name: 'UnitedHealth', sector: 'Health Care', mcap: 500, px: 542.80, pe: 19.8, yld: 1.5 },
  { sym: 'JNJ', name: 'Johnson & Johnson', sector: 'Health Care', mcap: 380, px: 158.20, pe: 15.3, yld: 3.0 },
  { sym: 'ABBV', name: 'AbbVie', sector: 'Health Care', mcap: 300, px: 170.40, pe: 60.2, yld: 3.6 },
  { sym: 'MRK', name: 'Merck', sector: 'Health Care', mcap: 260, px: 103.10, pe: 15.0, yld: 3.0 },
  { sym: 'TMO', name: 'Thermo Fisher', sector: 'Health Care', mcap: 210, px: 550.40, pe: 36.2, yld: 0.3 },
  { sym: 'AMGN', name: 'Amgen', sector: 'Health Care', mcap: 170, px: 318.20, pe: 47.0, yld: 2.8 },
  { sym: 'PFE', name: 'Pfizer', sector: 'Health Care', mcap: 160, px: 28.40, pe: 13.1, yld: 5.9 },
  // Energy
  { sym: 'XOM', name: 'ExxonMobil', sector: 'Energy', mcap: 498, px: 115.40, pe: 13.7, yld: 3.4 },
  { sym: 'CVX', name: 'Chevron', sector: 'Energy', mcap: 270, px: 146.20, pe: 13.9, yld: 4.4 },
  { sym: 'COP', name: 'ConocoPhillips', sector: 'Energy', mcap: 130, px: 110.30, pe: 12.1, yld: 3.1 },
  { sym: 'EOG', name: 'EOG Resources', sector: 'Energy', mcap: 70, px: 122.40, pe: 10.4, yld: 3.0 },
  { sym: 'SLB', name: 'SLB', sector: 'Energy', mcap: 60, px: 42.10, pe: 13.0, yld: 2.6 },
  { sym: 'MPC', name: 'Marathon Petroleum', sector: 'Energy', mcap: 60, px: 170.20, pe: 11.2, yld: 2.0 },
  { sym: 'VLO', name: 'Valero Energy', sector: 'Energy', mcap: 50, px: 152.30, pe: 11.0, yld: 2.8 },
  // Consumer Cyclical
  { sym: 'AMZN', name: 'Amazon', sector: 'Consumer Cyclical', mcap: 2050, px: 196.40, pe: 47.8, yld: 0.0 },
  { sym: 'TSLA', name: 'Tesla', sector: 'Consumer Cyclical', mcap: 794, px: 248.90, pe: 64.0, yld: 0.0 },
  { sym: 'HD', name: 'Home Depot', sector: 'Consumer Cyclical', mcap: 360, px: 365.10, pe: 24.3, yld: 2.5 },
  { sym: 'MCD', name: "McDonald's", sector: 'Consumer Cyclical', mcap: 215, px: 295.40, pe: 26.0, yld: 2.3 },
  { sym: 'NKE', name: 'Nike', sector: 'Consumer Cyclical', mcap: 110, px: 72.30, pe: 27.2, yld: 2.1 },
  { sym: 'SBUX', name: 'Starbucks', sector: 'Consumer Cyclical', mcap: 105, px: 92.10, pe: 28.0, yld: 2.5 },
  // Consumer Defensive
  { sym: 'WMT', name: 'Walmart', sector: 'Consumer Defensive', mcap: 600, px: 74.30, pe: 31.2, yld: 1.2 },
  { sym: 'PG', name: 'Procter & Gamble', sector: 'Consumer Defensive', mcap: 400, px: 170.20, pe: 27.0, yld: 2.4 },
  { sym: 'COST', name: 'Costco', sector: 'Consumer Defensive', mcap: 392, px: 884.20, pe: 54.0, yld: 0.5 },
  { sym: 'KO', name: 'Coca-Cola', sector: 'Consumer Defensive', mcap: 290, px: 68.10, pe: 26.1, yld: 2.9 },
  { sym: 'PEP', name: 'PepsiCo', sector: 'Consumer Defensive', mcap: 230, px: 168.40, pe: 22.3, yld: 3.2 },
  { sym: 'PM', name: 'Philip Morris', sector: 'Consumer Defensive', mcap: 190, px: 122.20, pe: 20.4, yld: 4.3 },
  // Industrials
  { sym: 'GE', name: 'GE Aerospace', sector: 'Industrials', mcap: 180, px: 165.30, pe: 35.1, yld: 0.7 },
  { sym: 'CAT', name: 'Caterpillar', sector: 'Industrials', mcap: 170, px: 350.20, pe: 17.3, yld: 1.5 },
  { sym: 'UNP', name: 'Union Pacific', sector: 'Industrials', mcap: 140, px: 235.10, pe: 22.0, yld: 2.3 },
  { sym: 'HON', name: 'Honeywell', sector: 'Industrials', mcap: 130, px: 200.40, pe: 21.2, yld: 2.2 },
  { sym: 'BA', name: 'Boeing', sector: 'Industrials', mcap: 110, px: 178.20, pe: null, yld: 0.0 },
  { sym: 'DE', name: 'Deere', sector: 'Industrials', mcap: 100, px: 370.40, pe: 12.4, yld: 1.6 },
  // Utilities
  { sym: 'NEE', name: 'NextEra Energy', sector: 'Utilities', mcap: 150, px: 73.20, pe: 21.0, yld: 2.9 },
  { sym: 'SO', name: 'Southern Co', sector: 'Utilities', mcap: 90, px: 82.40, pe: 21.3, yld: 3.9 },
  { sym: 'DUK', name: 'Duke Energy', sector: 'Utilities', mcap: 80, px: 104.10, pe: 19.2, yld: 4.0 },
  { sym: 'AEP', name: 'American Electric', sector: 'Utilities', mcap: 50, px: 95.30, pe: 18.0, yld: 3.7 },
  // Materials
  { sym: 'LIN', name: 'Linde', sector: 'Materials', mcap: 220, px: 458.20, pe: 33.1, yld: 1.2 },
  { sym: 'FCX', name: 'Freeport-McMoRan', sector: 'Materials', mcap: 60, px: 42.30, pe: 30.0, yld: 1.5 },
  { sym: 'NEM', name: 'Newmont', sector: 'Materials', mcap: 50, px: 44.10, pe: 15.2, yld: 2.3 },
  // Real Estate
  { sym: 'PLD', name: 'Prologis', sector: 'Real Estate', mcap: 100, px: 108.20, pe: 35.0, yld: 3.6 },
  { sym: 'AMT', name: 'American Tower', sector: 'Real Estate', mcap: 90, px: 195.40, pe: 45.2, yld: 3.3 },
  { sym: 'SPG', name: 'Simon Property', sector: 'Real Estate', mcap: 55, px: 168.30, pe: 22.1, yld: 5.2 },
];

const SCR_SECTOR_ORDER = ['Technology', 'Communications', 'Financials', 'Consumer Cyclical',
  'Health Care', 'Consumer Defensive', 'Energy', 'Industrials', 'Utilities', 'Materials', 'Real Estate'];

// ---------- deterministic % change model ----------
const SCR_PERIODS = {
  '1D':  { range: 1.8, cap: 3 },
  '1W':  { range: 3.8, cap: 6 },
  '1M':  { range: 8.0, cap: 12 },
  'YTD': { range: 18.0, cap: 30 },
};
// sector tilts that echo the front-page stories (oil drop, M&A thaw, copper bid)
const SCR_BIAS = {
  '1D':  { Energy: -2.6, Technology: 0.7, Communications: 0.5, Financials: 0.6, Materials: 1.0, 'Consumer Cyclical': 0.2, 'Health Care': -0.2, Utilities: 0.1, 'Consumer Defensive': 0.0, Industrials: 0.2, 'Real Estate': 0.3 },
  '1W':  { Energy: -3.4, Technology: 2.0, Communications: 1.4, Financials: 1.6, Materials: 2.2, 'Consumer Cyclical': 0.6, 'Health Care': 0.2, Utilities: 0.6, 'Consumer Defensive': 0.3, Industrials: 0.8, 'Real Estate': 1.0 },
  '1M':  { Energy: -4.5, Technology: 4.2, Communications: 3.0, Financials: 3.4, Materials: 3.8, 'Consumer Cyclical': 1.4, 'Health Care': 0.8, Utilities: 1.6, 'Consumer Defensive': 0.6, Industrials: 2.0, 'Real Estate': 2.4 },
  'YTD': { Energy: -7.5, Technology: 12.5, Communications: 9.0, Financials: 8.5, Materials: 6.5, 'Consumer Cyclical': 4.0, 'Health Care': 2.5, Utilities: 4.5, 'Consumer Defensive': 2.0, Industrials: 5.0, 'Real Estate': 3.5 },
};
// hand-pinned names so the tape tells the same story everywhere
const SCR_OVERRIDE = {
  '1D': { XOM: -3.9, CVX: -3.2, COP: -4.3, EOG: -4.1, SLB: -3.7, MPC: 2.6, VLO: 2.3, FCX: 3.2, NEM: 1.1, NVDA: 1.7, TSLA: -1.9, BA: -1.6, LLY: 1.2, GS: 1.4, MS: 1.1 },
  '1W': { MPC: 4.8, VLO: 4.2, FCX: 6.1, GS: 3.8, MS: 3.2, JPM: 2.9, BA: -3.4 },
  'YTD': { NVDA: 34.2, META: 18.4, GS: 16.8, FCX: 22.5, INTC: -14.2, BA: -18.6, NKE: -9.4, TSLA: -6.8 },
};

function scrSeed(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = (h * 16777619) >>> 0; }
  return h >>> 0;
}
function scrRng(seed) { let s = seed || 1; return () => { s = (s * 1664525 + 1013904223) >>> 0; return s / 4294967296; }; }

const SCR_CHG_CACHE = {};
function scrChg(sym, period) {
  const key = sym + ':' + period;
  if (key in SCR_CHG_CACHE) return SCR_CHG_CACHE[key];
  const ov = (SCR_OVERRIDE[period] || {})[sym];
  let v;
  if (ov !== undefined) v = ov;
  else {
    const st = SCR_STOCKS.find(s => s.sym === sym);
    const p = SCR_PERIODS[period];
    const r = scrRng(scrSeed(key + ':v3'));
    const noise = (r() + r() + r()) / 3 - 0.5; // ~bell-shaped
    v = noise * 2 * p.range + ((SCR_BIAS[period] || {})[st && st.sector] || 0);
    v = Math.round(v * 10) / 10;
  }
  SCR_CHG_CACHE[key] = v;
  return v;
}

// 90-day price walk ending on today's price, shaped by YTD direction
function scrSeries(sym, n) {
  n = n || 90;
  const st = SCR_STOCKS.find(s => s.sym === sym);
  const ytd = scrChg(sym, 'YTD');
  const r = scrRng(scrSeed(sym + ':series'));
  const out = []; let v = 100;
  for (let i = 0; i < n; i++) { out.push(v); v += (r() - 0.5) * 1.6; }
  const drift = ytd * 0.6; // 90d ≈ 60% of the YTD move
  const adj = (100 + drift) - out[n - 1];
  const shaped = out.map((x, i) => x + adj * (i / (n - 1)));
  const k = st.px / shaped[n - 1];
  return shaped.map(x => x * k);
}

function scrFmtCap(b) { return b >= 1000 ? (b / 1000).toFixed(2) + 'T' : b.toFixed(0) + 'B'; }
function scrFmtChg(v) { return (v > 0 ? '+' : v < 0 ? '−' : '') + Math.abs(v).toFixed(1) + '%'; }
function scrFmtPx(v) { return v >= 1000 ? v.toLocaleString('en-US', { maximumFractionDigits: 0 }) : v.toFixed(2); }

Object.assign(window, { SCR_STOCKS, SCR_SECTOR_ORDER, SCR_PERIODS, scrChg, scrSeries, scrFmtCap, scrFmtChg, scrFmtPx });
