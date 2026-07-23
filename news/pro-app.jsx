// pro-app.jsx — page composition for News Desk Pro.
// Pulls story content from data.jsx (CLUSTERS, BRIEFS, DEFAULT_SOURCES),
// charts from pro-charts.jsx, tweaks shell from tweaks-panel.jsx.

const { useEffect } = React;

// ---------- source lookup ----------
const SRC_NAME = {};
(window.DEFAULT_SOURCES || []).forEach(s => { SRC_NAME[s.id] = s.name; });
SRC_NAME.espn = 'ESPN';
function srcName(id) { return SRC_NAME[id] || id; }

const TOPIC_LABEL = {
  markets: 'Markets', business: 'Business', tech: 'Technology',
  politics: 'Politics', sports: 'Sports', world: 'World', opinion: 'Opinion',
};

// ---------- masthead + strap ----------
const TAPE = [
  { sym: 'S&P 500', px: '5,824.31', chg: '+0.4%', up: true },
  { sym: 'NASDAQ', px: '19,244.10', chg: '+0.7%', up: true },
  { sym: 'DOW', px: '41,712.04', chg: '+0.1%', up: true },
  { sym: 'US 10Y', px: '4.15%', chg: '−6bp', up: false },
  { sym: 'US 2Y', px: '4.11%', chg: '−11bp', up: false },
  { sym: 'WTI', px: '$75.28', chg: '−4.1%', up: false },
  { sym: 'GOLD', px: '$2,351', chg: '+0.1%', up: true },
  { sym: 'BTC', px: '$92,840', chg: '+0.9%', up: true },
  { sym: 'EUR/USD', px: '1.0812', chg: '+0.2%', up: true },
  { sym: 'COPPER', px: '$4.61', chg: '+1.8%', up: true },
  { sym: 'DXY', px: '104.41', chg: '−0.2%', up: false },
];

function Strap() {
  const today = new Date().toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' });
  return (
    <div className="strap" data-screen-label="Top strap">
      <div className="strap-in">
        <span className="strap-date">{today}</span>
        <span className="strap-status"><span className="live-dot"></span>U.S. markets open</span>
        <div className="tape" aria-label="Market ticker">
          <div className="tape-track">
            {[0, 1].map(rep => (
              <div className="tape-run" key={rep} aria-hidden={rep === 1}>
                {TAPE.map(t => (
                  <span className="tape-item" key={rep + t.sym}>
                    <span className="tape-sym">{t.sym}</span>
                    <span className="tape-px">{t.px}</span>
                    <span className={'tape-chg ' + (t.up ? 'is-up' : 'is-down')}>{t.chg}</span>
                  </span>
                ))}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Masthead({ view, onNav }) {
  const items = [
    { label: 'Top', view: 'top' }, { label: 'Markets', view: 'markets' },
    { label: 'Business' }, { label: 'Technology' }, { label: 'Politics' },
    { label: 'World' }, { label: 'Sports' }, { label: 'Data Desk' },
  ];
  return (
    <header className="mast" data-screen-label="Masthead">
      <div className="mast-in">
        <div className="mast-brand">
          <h1 className="brand">The Daily Brief</h1>
          <p className="brand-tag">Markets · Business · Power — your sources, one desk</p>
        </div>
        <div className="mast-side">
          <span className="edition">U.S. EDITION</span>
          <button className="btn-sub" type="button">My sources</button>
        </div>
      </div>
      <nav className="nav" aria-label="Sections">
        <div className="nav-in">
          {items.map(it => (
            <a key={it.label} href="#" className={'nav-link' + (it.view === view ? ' is-on' : '')}
               onClick={e => { e.preventDefault(); if (it.view) onNav(it.view); }}>{it.label}</a>
          ))}
          <span className="nav-spacer"></span>
          <a className="nav-link" href="/">📊 Dashboard</a>
          <span className="nav-search">⌕ Search</span>
        </div>
      </nav>
    </header>
  );
}

// ---------- hero ----------
function Hero({ showAnno }) {
  const c = (window.CLUSTERS || []).find(x => x.id === 'c1');
  if (!c) return null;
  return (
    <section className="hero" data-screen-label="Lead story">
      <div className="hero-text">
        <p className="kicker">Markets · Lead story</p>
        <h2 className="hero-hed">{c.headline}</h2>
        <p className="hero-dek">{c.dek}</p>
        <p className="hero-meta">3 hours ago · {c.stories.length} sources covering</p>
        <div className="coverage">
          <p className="coverage-label">Coverage</p>
          {c.stories.slice(0, 4).map((s, i) => (
            <a key={i} href="#" className="coverage-link" onClick={e => e.preventDefault()}>
              <span className="coverage-src">{srcName(s.source)}</span>
              <span className="coverage-title">{s.title}</span>
              <span className="coverage-min">{s.minutes} min</span>
            </a>
          ))}
        </div>
      </div>
      <div className="hero-chart">
        <YieldSpreadChart showAnno={showAnno} />
      </div>
    </section>
  );
}

// ---------- index strip ----------
const STRIP = [
  { name: 'S&P 500', px: '5,824.31', chg: '+0.4%', up: true, keys: [[0, 100], [30, 99.2], [55, 101.1], [80, 100.4], [100, 101.6]] },
  { name: 'Nasdaq', px: '19,244.10', chg: '+0.7%', up: true, keys: [[0, 100], [25, 100.8], [50, 100.2], [75, 101.4], [100, 102.1]] },
  { name: 'US 10Y', px: '4.15%', chg: '−6bp', up: false, keys: [[0, 100], [30, 100.3], [55, 99.6], [80, 99.2], [100, 98.8]] },
  { name: 'WTI crude', px: '$75.28', chg: '−4.1%', up: false, keys: [[0, 100], [20, 99.6], [40, 99.8], [60, 96.8], [100, 95.9]] },
  { name: 'Bitcoin', px: '$92,840', chg: '+0.9%', up: true, keys: [[0, 100], [35, 99.4], [60, 100.6], [100, 101.0]] },
  { name: 'Euro', px: '1.0812', chg: '+0.2%', up: true, keys: [[0, 100], [40, 99.9], [70, 100.1], [100, 100.2]] },
];

function IndexStrip() {
  return (
    <section className="strip" data-screen-label="Markets strip">
      {STRIP.map(s => (
        <div className="strip-card" key={s.name}>
          <div className="strip-top">
            <span className="strip-name">{s.name}</span>
            <span className={'strip-chg ' + (s.up ? 'is-up' : 'is-down')}>{s.chg}</span>
          </div>
          <div className="strip-px">{s.px}</div>
          <MiniLine keys={s.keys} dir={s.up ? 'up' : 'down'} label="" w={220} h={44} />
        </div>
      ))}
    </section>
  );
}

// ---------- data desk ----------
function DataDesk({ showAnno }) {
  return (
    <section className="desk" data-screen-label="Data Desk">
      <div className="desk-head">
        <h2 className="section-hed">Data Desk</h2>
        <p className="section-sub">The week&rsquo;s numbers, charted by our graphics team</p>
      </div>
      <div className="desk-grid">
        <RecessionCallsChart showAnno={showAnno} />
        <DealVolumeChart showAnno={showAnno} />
        <RecessionOddsChart showAnno={showAnno} />
      </div>
    </section>
  );
}

// ---------- story cards ----------
const CARD_CHARTS = {
  c6: { keys: [[0, 78.45], [20, 78.6], [40, 78.1], [55, 76.2], [75, 75.6], [100, 75.28]], dir: 'down', label: '$75.28' },
  c9: { keys: [[0, 11.84], [25, 11.9], [50, 12.2], [75, 12.6], [100, 13.05]], dir: 'up', label: '$13.05' },
  c8: { keys: [[0, 142], [30, 138], [55, 131], [80, 124], [100, 118]], dir: 'down', label: '$118B' },
};
const CARD_IDS = ['c2', 'c6', 'c3', 'c9', 'c8', 'c11', 'c5', 'c7'];

function StoryCard({ c }) {
  const chart = CARD_CHARTS[c.id];
  const lead = c.stories[0];
  return (
    <article className="card">
      <p className="kicker">{TOPIC_LABEL[c.topic] || c.topic}</p>
      <h3 className="card-hed">{c.headline}</h3>
      {chart ? <MiniLine keys={chart.keys} dir={chart.dir} label={chart.label} w={340} h={92} /> : null}
      <p className="card-dek">{c.dek}</p>
      <p className="card-meta">
        <span className="card-src">{srcName(lead.source)}</span>
        <span> +{c.stories.length - 1} more · {c.hours}h ago</span>
      </p>
    </article>
  );
}

function Rail() {
  const briefs = (window.BRIEFS || []).slice(0, 14);
  return (
    <aside className="rail" data-screen-label="Latest rail">
      <h2 className="rail-hed">The Tape</h2>
      <div className="rail-list">
        {briefs.map((b, i) => (
          <a key={i} href="#" className="rail-item" onClick={e => e.preventDefault()}>
            <span className="rail-meta">
              <span className="rail-src">{srcName(b.source)}</span>
              {(b.flags || []).map(f => <span key={f} className="flag">{f}</span>)}
            </span>
            <span className="rail-title">{b.title}</span>
          </a>
        ))}
      </div>
    </aside>
  );
}

function StorySection() {
  const byId = {}; (window.CLUSTERS || []).forEach(c => { byId[c.id] = c; });
  const cards = CARD_IDS.map(id => byId[id]).filter(Boolean);
  return (
    <section className="stories" data-screen-label="Story grid">
      <div className="stories-main">
        {cards.map(c => <StoryCard key={c.id} c={c} />)}
      </div>
      <Rail />
    </section>
  );
}

function Footer() {
  return (
    <footer className="foot" data-screen-label="Footer">
      <div className="foot-in">
        <span className="foot-brand">The Daily Brief</span>
        <span className="foot-note">Personal news intelligence — built from your subscriptions. All figures illustrative.</span>
      </div>
    </footer>
  );
}

// ---------- app + tweaks ----------
const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "accent": "#2456c4",
  "density": "regular",
  "annotations": true,
  "headlineFont": "franklin"
}/*EDITMODE-END*/;

function App() {
  const [t, setTweak] = useTweaks(TWEAK_DEFAULTS);
  const [view, setView] = React.useState(() => (location.hash || '').includes('markets') ? 'markets' : 'top');
  useEffect(() => {
    const id = view === 'markets' ? '#markets' : '#top';
    if (location.hash !== id) { try { history.replaceState(null, '', id); } catch (e) {} }
    window.scrollTo(0, 0);
  }, [view]);
  useEffect(() => {
    const r = document.documentElement;
    r.style.setProperty('--accent', t.accent);
    r.dataset.density = t.density;
    r.dataset.hed = t.headlineFont;
  }, [t.accent, t.density, t.headlineFont]);
  return (
    <div className="page">
      <Strap />
      <Masthead view={view} onNav={setView} />
      <main className="main">
        {view === 'markets' ? (
          <MarketsView />
        ) : (
          <React.Fragment>
            <Hero showAnno={t.annotations} />
            <IndexStrip />
            <DataDesk showAnno={t.annotations} />
            <SectorMultiples />
            <StorySection />
          </React.Fragment>
        )}
      </main>
      <Footer />
      <TweaksPanel>
        <TweakSection label="Color" />
        <TweakColor label="Accent" value={t.accent}
                    options={["#2456c4", "#0f7a4a", "#b3470e", "#16181c"]}
                    onChange={v => setTweak('accent', v)} />
        <TweakSection label="Layout" />
        <TweakRadio label="Density" value={t.density}
                    options={["compact", "regular", "comfy"]}
                    onChange={v => setTweak('density', v)} />
        <TweakSection label="Charts" />
        <TweakToggle label="Annotations" value={t.annotations}
                     onChange={v => setTweak('annotations', v)} />
        <TweakSection label="Type" />
        <TweakRadio label="Headlines" value={t.headlineFont}
                    options={["franklin", "serif"]}
                    onChange={v => setTweak('headlineFont', v)} />
      </TweaksPanel>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
