// data.jsx — sources reflect the user's stated subscription stack
// Subscribed: WSJ, FT, Bloomberg, The Athletic
// Other followed: NYT, Reuters, Axios, plus X accounts and YouTube channels

const DEFAULT_SOURCES = [
  // — paid subscriptions —
  { id: 'wsj',       name: 'Wall Street Journal', kind: 'site',     subscribed: true,  handle: 'wsj.com' },
  { id: 'ft',        name: 'Financial Times',     kind: 'site',     subscribed: true,  handle: 'ft.com' },
  { id: 'bloomberg', name: 'Bloomberg',           kind: 'site',     subscribed: true,  handle: 'bloomberg.com' },
  { id: 'athletic',  name: 'The Athletic',        kind: 'site',     subscribed: true,  handle: 'theathletic.com' },
  // — followed sites —
  { id: 'nyt',       name: 'New York Times',      kind: 'site',     subscribed: false, handle: 'nytimes.com' },
  { id: 'reuters',   name: 'Reuters',             kind: 'site',     subscribed: false, handle: 'reuters.com' },
  { id: 'axios',     name: 'Axios',               kind: 'site',     subscribed: false, handle: 'axios.com' },
  { id: 'economist', name: 'The Economist',       kind: 'site',     subscribed: false, handle: 'economist.com' },
  { id: 'cnbc',      name: 'CNBC',                kind: 'site',     subscribed: false, handle: 'cnbc.com' },
  // — X (Twitter) accounts —
  { id: 'x_lisa',    name: 'Lisa Abramowicz',     kind: 'x',        subscribed: false, handle: '@lisaabramowicz1', tags: ['Markets','Macro'],         notify: 'normal', followers: '180K' },
  { id: 'x_zh',      name: 'Zerohedge',           kind: 'x',        subscribed: false, handle: '@zerohedge',       tags: ['Markets','Contrarian'],    notify: 'low',    followers: '1.8M' },
  { id: 'x_swisher', name: 'Kara Swisher',        kind: 'x',        subscribed: false, handle: '@karaswisher',     tags: ['Tech','Media'],            notify: 'normal', followers: '1.4M' },
  { id: 'x_woj',     name: 'Adrian Wojnarowski',  kind: 'x',        subscribed: false, handle: '@wojespn',         tags: ['Sports','Breaking'],       notify: 'high',   followers: '6.0M' },
  { id: 'x_levine',  name: 'Matt Levine',         kind: 'x',        subscribed: false, handle: '@matt_levine',     tags: ['Markets','Long-form'],     notify: 'normal', followers: '320K' },
  // — YouTube —
  { id: 'yt_aw',     name: 'All-In Podcast',      kind: 'youtube',  subscribed: false, handle: '@allin',           tags: ['Tech','Politics'],         notify: 'normal', subs: '1.2M', cadence: 'Weekly' },
  { id: 'yt_bg',     name: 'Bg2 Pod',             kind: 'youtube',  subscribed: false, handle: '@bg2pod',          tags: ['Tech','VC'],               notify: 'normal', subs: '210K', cadence: 'Weekly' },
  { id: 'yt_acq',    name: 'Acquired',            kind: 'youtube',  subscribed: false, handle: '@acquiredfm',      tags: ['Business','Long-form'],    notify: 'high',   subs: '780K', cadence: 'Bi-weekly' },
];

const DEFAULT_TOPICS = [
  { id: 'markets',  name: 'Markets & Macro',  enabled: true },
  { id: 'business', name: 'Business & Deals', enabled: true },
  { id: 'tech',     name: 'Tech & AI',        enabled: true },
  { id: 'politics', name: 'Politics & Policy', enabled: true },
  { id: 'sports',   name: 'Sports',           enabled: true },
  { id: 'world',    name: 'World',            enabled: true },
  { id: 'opinion',  name: 'Opinion & Analysis', enabled: false },
];

// Each cluster: a story arc covered by multiple sources.
const CLUSTERS = [
  {
    id: 'c1', topic: 'markets',
    headline: 'Yield curve un-inverts after 28-month stretch — strategists rip up recession scripts',
    dek: 'The 2s/10s spread crossed back into positive territory after the longest inversion since the 1980s, prompting a flurry of recession-call retractions across the Street.',
    weight: 96, hours: 3,
    take: "Bloomberg's chart pack is the cleanest read; FT's piece adds the most institutional context.",
    stories: [
      { source: 'bloomberg', title: '2s/10s flips positive — what it means now', minutes: 5 },
      { source: 'wsj',       title: 'Wall Street walks back the recession call', minutes: 8 },
      { source: 'ft',        title: 'Strategists pivot as curve un-inverts', minutes: 7 },
      { source: 'reuters',   title: 'Treasury curve normalizes for first time since 2023', minutes: 4 },
      { source: 'x_levine',  title: 'Money Stuff: the curve, the call, the cope', minutes: 9 },
      { source: 'x_lisa',    title: 'Thread: what un-inversion historically means →', minutes: 3 },
    ],
  },
  {
    id: 'c2', topic: 'tech',
    headline: 'OpenAI, Anthropic, Google ship persistent-memory agents within ten days of each other',
    dek: 'Three frontier labs released long-horizon memory features in rapid succession. Enterprise buyers are scrambling; competitors are arguing about whether memory is a moat or a commodity.',
    weight: 91, hours: 6,
    take: 'WSJ has the enterprise angle; Axios has the cleanest framing of the strategic stakes.',
    stories: [
      { source: 'wsj',     title: 'AI agents that remember everything are here', minutes: 9 },
      { source: 'nyt',     title: 'A quiet shift toward "agentic" AI', minutes: 11 },
      { source: 'axios',   title: '1 big thing: memory is the new context window', minutes: 4 },
      { source: 'reuters', title: 'OpenAI rolls out persistent memory to enterprise', minutes: 5 },
      { source: 'yt_bg',   title: 'Bg2: the memory wars (with guest)', minutes: 84 },
      { source: 'x_swisher', title: '"Memory changes everything" — short take', minutes: 2 },
    ],
  },
  {
    id: 'c3', topic: 'business',
    headline: 'Mega-deal week: three $20B+ takeovers announced inside 72 hours',
    dek: 'Activist pressure, cheap debt windows, and a softer antitrust stance combined to unlock the busiest M&A stretch since 2021. Bankers are calling it the thaw.',
    weight: 84, hours: 11,
    take: "FT's lex column is the sharpest; Bloomberg has the league tables.",
    stories: [
      { source: 'ft',        title: 'Lex: the deal thaw is real', minutes: 6 },
      { source: 'bloomberg', title: 'M&A bankers post best week since 2021', minutes: 7 },
      { source: 'wsj',       title: 'Inside the three deals that broke the dam', minutes: 12 },
      { source: 'cnbc',      title: 'Deal premium math is back, baby', minutes: 4 },
    ],
  },
  {
    id: 'c4', topic: 'sports',
    headline: 'Trade deadline turns into a sell-off as five contenders quietly retool',
    dek: 'What looked like a buyer\u2019s market a month ago has flipped. Front offices are citing salary cap math and a wide-open conference race as reasons to pull back.',
    weight: 72, hours: 14,
    take: 'The Athletic has the front-office reporting; Woj has the breaking pieces.',
    stories: [
      { source: 'athletic', title: 'Why five contenders are suddenly sellers', minutes: 13 },
      { source: 'athletic', title: 'Cap math: the trades that don\u2019t pencil', minutes: 9 },
      { source: 'x_woj',    title: 'BREAKING: All-Star forward on the move →', minutes: 1 },
      { source: 'espn',     title: 'Deadline winners and losers, early read', minutes: 6 },
    ],
  },
  {
    id: 'c5', topic: 'politics',
    headline: 'EU AI model registry goes live — first compliance window closes June 1',
    dek: 'The registry covers any model trained above a 10^25 FLOP threshold or deployed to over one million EU users. Initial filings reveal more about training data than most expected.',
    weight: 66, hours: 19,
    take: "FT has the cleanest reporting; NYT goes deepest on the political backstory.",
    stories: [
      { source: 'ft',      title: 'Inside the EU\u2019s first batch of model filings', minutes: 9 },
      { source: 'nyt',     title: 'How Brussels won the AI rules race', minutes: 14 },
      { source: 'reuters', title: 'US labs grumble, comply', minutes: 5 },
      { source: 'axios',   title: '1 chart: who filed, who didn\u2019t', minutes: 3 },
    ],
  },
  {
    id: 'c6', topic: 'markets',
    headline: 'Oil drops 4% on surprise OPEC+ output bump; refiners catch a bid',
    dek: 'A larger-than-expected production increase, telegraphed only late on Sunday, sent crude tumbling into Monday open. Refining margins reacted in the opposite direction.',
    weight: 58, hours: 22,
    take: 'Reuters had it first; FT has the political angle.',
    stories: [
      { source: 'reuters',   title: 'OPEC+ surprises with bigger output hike', minutes: 4 },
      { source: 'bloomberg', title: 'Crude breaks support; refiners rally', minutes: 5 },
      { source: 'ft',        title: 'Why Riyadh changed its mind', minutes: 9 },
      { source: 'x_zh',      title: 'Algo carnage in energy futures →', minutes: 2 },
    ],
  },
  {
    id: 'c7', topic: 'tech',
    headline: 'Apple\u2019s next chip family leaks: 3nm successor, neural engine doubled',
    dek: 'Slides circulating among contract partners suggest a substantially redesigned NPU and a small but meaningful CPU bump. Shipment timing remains the open question.',
    weight: 54, hours: 26,
    take: 'NYT has the supply-chain reporting; All-In has a fun back-and-forth about the strategy.',
    stories: [
      { source: 'nyt',     title: 'Apple\u2019s next silicon, charted', minutes: 8 },
      { source: 'wsj',     title: 'Why Apple\u2019s chip cadence matters more this year', minutes: 9 },
      { source: 'yt_aw',   title: 'All-In: the Apple silicon question', minutes: 62 },
      { source: 'x_swisher', title: '"Stop calling it AI Pro" — quick take', minutes: 1 },
    ],
  },
  {
    id: 'c8', topic: 'business',
    headline: 'Private credit\u2019s "denominator problem" finally hits university endowments',
    dek: 'Three large endowments quietly halted new private commitments this quarter. The math caught up to the fundraising pitch.',
    weight: 49, hours: 31,
    take: "FT's Alphaville has the best technical breakdown; Matt Levine\u2019s column is required reading.",
    stories: [
      { source: 'ft',        title: 'The private credit denominator, charted', minutes: 10 },
      { source: 'bloomberg', title: 'Endowments hit pause', minutes: 6 },
      { source: 'x_levine',  title: 'Money Stuff: maybe everyone owns the same thing', minutes: 11 },
    ],
  },
  {
    id: 'c9', topic: 'world',
    headline: 'Drought along the Paraná disrupts a fifth of South American grain logistics',
    dek: 'Unusually low water levels are forcing barges to lighten loads and rerouting cargo through more expensive rail corridors. Soft commodity prices are responding.',
    weight: 38, hours: 38,
    take: 'Reuters has the on-the-ground reporting.',
    stories: [
      { source: 'reuters',   title: 'Paraná river levels hit decade low', minutes: 6 },
      { source: 'ft',        title: 'Grain prices climb on logistics squeeze', minutes: 7 },
      { source: 'bloomberg', title: 'Soybean futures break out', minutes: 4 },
    ],
  },
  {
    id: 'c10', topic: 'sports',
    headline: 'Champions League upset reshuffles knockout-round seeding',
    dek: 'A second-leg result no one had on their card has bumped two heavyweights into a much harder bracket. Bookmakers spent Monday rewriting odds.',
    weight: 41, hours: 24,
    take: 'Athletic\u2019s tactical breakdown is the standout.',
    stories: [
      { source: 'athletic', title: 'How they actually won, in three set pieces', minutes: 11 },
      { source: 'athletic', title: 'The seeding math, explained', minutes: 6 },
      { source: 'reuters',  title: 'Match report and reaction', minutes: 4 },
    ],
  },
  {
    id: 'c11', topic: 'politics',
    headline: 'Senate finally moves on stablecoin framework after 18-month standoff',
    dek: 'A bipartisan bill cleared committee with surprising margins. Banks are cautiously supportive; crypto-native firms are split.',
    weight: 44, hours: 16,
    take: 'WSJ has the policy reporting; Axios has the political horse-race read.',
    stories: [
      { source: 'wsj',     title: 'Stablecoin bill clears committee, 18\u20136', minutes: 8 },
      { source: 'axios',   title: 'Behind the unexpected vote tally', minutes: 4 },
      { source: 'reuters', title: 'Banks shift posture on stablecoins', minutes: 5 },
    ],
  },
  {
    id: 'c12', topic: 'tech',
    headline: 'Open-weights coalition publishes shared evaluation harness',
    dek: 'Eight labs, four academic groups, and two governments signed onto a common eval suite — the first credible attempt at apples-to-apples benchmarking since the closed-source turn.',
    weight: 36, hours: 30,
    take: 'The Bg2 deep dive is the best long form.',
    stories: [
      { source: 'yt_bg',   title: 'Bg2: a common eval, finally', minutes: 71 },
      { source: 'reuters', title: 'OpenEval v1 released', minutes: 4 },
      { source: 'axios',   title: 'Why this matters for AI procurement', minutes: 3 },
    ],
  },
];

// Drudge-style dense link items (single-source briefs and headlines)
const BRIEFS = [
  { source: 'wsj',       title: 'BREAKING: Fed\u2019s Williams hints at one more cut by year-end', flags: ['BREAKING'] },
  { source: 'bloomberg', title: 'Yen weakens past 162; intervention chatter resumes' },
  { source: 'ft',        title: 'German industrial orders post fourth straight monthly drop' },
  { source: 'reuters',   title: 'Boeing pauses 737 deliveries to two carriers pending audit' },
  { source: 'x_woj',     title: 'Sources: starting PG dealt for picks, swap, and a young wing →', flags: ['SCOOP'] },
  { source: 'athletic',  title: 'How a backup goalie became the most important trade chip in MLS' },
  { source: 'x_levine',  title: 'A bond just defaulted in a really funny way' },
  { source: 'cnbc',      title: 'Retail earnings preview: who\u2019s actually growing' },
  { source: 'nyt',       title: 'Profile: the lawyer behind every recent antitrust win' },
  { source: 'axios',     title: '1 big thing: governors quietly preparing AI executive orders' },
  { source: 'wsj',       title: 'EXCLUSIVE: tech firm in talks to acquire DC lobbying shop', flags: ['EXCLUSIVE'] },
  { source: 'ft',        title: 'Lex in brief: why the LBO comeback is fragile' },
  { source: 'bloomberg', title: 'Credit spreads tightest since January despite issuance flood' },
  { source: 'x_zh',      title: 'Volatility regime change in two charts →' },
  { source: 'reuters',   title: 'India tightens rules on overseas listings' },
  { source: 'yt_acq',    title: 'New episode: the company that owns half the world\u2019s ports' },
  { source: 'wsj',       title: 'Office vacancy hits 21% in three biggest metros' },
  { source: 'nyt',       title: 'A small-town bank failure that mattered more than it should' },
  { source: 'axios',     title: 'Smart Brevity: the antitrust week ahead' },
  { source: 'bloomberg', title: 'Copper hits 18-month high on grid-buildout demand' },
  { source: 'athletic',  title: 'Five managers quietly on the hot seat heading into May' },
  { source: 'x_swisher', title: '"Founders are tired" — short essay →' },
  { source: 'ft',        title: 'EU energy ministers fail to agree on price cap extension' },
  { source: 'reuters',   title: 'Drugmaker pulls weight-loss study, cites enrollment issues' },
  { source: 'wsj',       title: 'Heard on the Street: bank stocks have a quiet quality problem' },
  { source: 'cnbc',      title: 'Mag 7 earnings scorecard: who beat, who guided down' },
  { source: 'bloomberg', title: 'Oil tankers idle off the Strait as insurers demand more cover' },
  { source: 'x_lisa',    title: 'Mortgage rate move you didn\u2019t see covered →' },
  { source: 'nyt',       title: 'Op-Ed: the case against \u201cbroad\u201d AI regulation' },
  { source: 'yt_aw',     title: 'All-In: the great state-tax migration, two years in' },
];

window.DEFAULT_SOURCES = DEFAULT_SOURCES;
window.DEFAULT_TOPICS = DEFAULT_TOPICS;
window.CLUSTERS = CLUSTERS;
window.BRIEFS = BRIEFS;
