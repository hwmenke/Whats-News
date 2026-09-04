import 'package:flutter/cupertino.dart';

import '../data/app_state.dart';
import '../data/models.dart';
import 'theme.dart';

/// Watchlist-scoped scans from the Python scanner — no Dart-side indicator math.
class ScansPage extends StatelessWidget {
  const ScansPage({
    super.key,
    required this.state,
    required this.onOpenChart,
  });

  final WhatsNewsState state;
  final ValueChanged<String> onOpenChart;

  @override
  Widget build(BuildContext context) {
    final status = state.scannerStatus;
    final running = status['running'] == true;
    return CustomScrollView(
      slivers: [
        CupertinoSliverNavigationBar(
          backgroundColor: DeskColors.elevated,
          largeTitle: const Text('Scans'),
          trailing: CupertinoButton(
            padding: EdgeInsets.zero,
            onPressed: state.loadingScans
                ? null
                : () {
                    state.loadScans();
                    state.loadMacro();
                  },
            child: const Icon(CupertinoIcons.refresh),
          ),
        ),
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Yahoo/SQLite scans · ENGINE + Market Moves. Empty = no bars.',
                  style: TextStyle(color: DeskColors.muted, fontSize: 11),
                ),
                const SizedBox(height: 6),
                _BreadthStrip(
                  breadth: state.scanBreadth,
                  engineReady: state.warningsBoard.ready,
                ),
                if (running)
                  const Padding(
                    padding: EdgeInsets.only(top: 6),
                    child: Text(
                      'S&P 500 archive fetch is running in the background.',
                      style: TextStyle(color: Color(0xFFEAB308), fontSize: 12),
                    ),
                  ),
                const SizedBox(height: 6),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      for (final e in const [
                        ('warnings', 'Warnings'),
                        ('command', 'Command'),
                        ('setup', 'Setup'),
                        ('pattern', 'Pattern'),
                        ('rsic', 'RSI-C'),
                        ('stretch', 'Stretch'),
                        ('sigma', 'Sigma'),
                        ('maps', 'Maps'),
                        ('moves', 'Moves'),
                        ('ma', 'MA'),
                        ('rsi', 'RSI'),
                        ('breakout', 'Breakout'),
                        ('qulla', 'Qulla'),
                        ('oneil', "O'Neil"),
                        ('vcp', 'VCP'),
                        ('edges', 'Edges'),
                        ('fractal', 'Fractal'),
                        ('finviz', 'Finviz'),
                        ('hmm', 'HMM'),
                        ('combo', 'Combo'),
                        ('setups', 'Setups'),
                        ('trend', 'Trend'),
                        ('metrics', 'Metrics'),
                      ])
                        Padding(
                          padding: const EdgeInsets.only(right: 4),
                          child: _ModeChip(
                            label: e.$2,
                            on: state.scanMode == e.$1,
                            onTap: () => state.setScanMode(e.$1),
                          ),
                        ),
                    ],
                  ),
                ),
                if (state.scanMode == 'qulla') ...[
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      for (final e in const [
                        ('all', 'All'),
                        ('ep', 'EP'),
                        ('breakout', 'Breakout'),
                        ('vol', 'Vol'),
                        ('adr', 'ADR≥4'),
                      ])
                        _ModeChip(
                          label: e.$2,
                          on: state.qullaFilter == e.$1,
                          onTap: () => state.setQullaFilter(e.$1),
                        ),
                    ],
                  ),
                ],
                if (state.scanMode == 'edges' && state.edgeTags.isNotEmpty) ...[
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 6,
                    runSpacing: 6,
                    children: [
                      for (final tag in state.edgeTags)
                        _ModeChip(
                          label: tag,
                          on: state.edgeTag == tag,
                          onTap: () => state.setEdgeTag(tag),
                        ),
                    ],
                  ),
                ],
                if (state.scanError != null) ...[
                  const SizedBox(height: 8),
                  Text(
                    state.scanError!,
                    style: const TextStyle(color: DeskColors.red, fontSize: 13),
                  ),
                ],
              ],
            ),
          ),
        ),
        if (state.scanMode == 'fractal')
          ..._fractalSlivers(state)
        else if (state.scanMode == 'finviz')
          ..._finvizSlivers(state)
        else if (state.scanMode == 'hmm')
          ..._hmmSlivers(state)
        else if (state.scanMode == 'combo')
          ..._comboSlivers(state)
        else if (state.scanMode == 'command')
          ..._commandSlivers(state)
        else if (state.scanMode == 'setup')
          ..._setupEngineSlivers(state)
        else if (state.scanMode == 'pattern')
          ..._patternSlivers(state)
        else if (state.scanMode == 'rsic')
          ..._rsicSlivers(state)
        else if (state.scanMode == 'stretch')
          ..._stretchSlivers(state)
        else if (state.scanMode == 'sigma')
          ..._sigmaSlivers(state)
        else if (state.scanMode == 'maps')
          ..._mapsSlivers(state)
        else if (state.scanMode == 'warnings')
          ..._warningsSlivers(state)
        else if (state.scanMode == 'moves')
          ..._movesSlivers(state)
        else if (state.scanMode == 'ma' ||
            state.scanMode == 'rsi' ||
            state.scanMode == 'breakout' ||
            state.scanMode == 'oneil' ||
            state.scanMode == 'vcp')
          ..._packSlivers(state)
        else if (state.scanMode == 'edges')
          ..._edgesSlivers(state)
        else if (state.loadingScans && _rowsEmpty(state))
          const SliverFillRemaining(
            child: Center(child: CupertinoActivityIndicator()),
          )
        else if (_rowsEmpty(state))
          const SliverFillRemaining(
            hasScrollBody: false,
            child: Padding(
              padding: EdgeInsets.all(24),
              child: Text(
                'No scan rows yet.\n\nSeed a Macro sleeve or Core 50, Fetch from Yahoo, then refresh. Empty is missing bars — not a fake print.',
                style: TextStyle(color: DeskColors.muted, height: 1.4),
              ),
            ),
          )
        else
          SliverPadding(
            padding: const EdgeInsets.only(bottom: 24),
            sliver: SliverList.separated(
              itemCount: _count(state),
              separatorBuilder: (_, _) => const Padding(
                padding: EdgeInsets.symmetric(horizontal: 16),
                child: ColoredBox(
                  color: DeskColors.border,
                  child: SizedBox(height: 0.5),
                ),
              ),
              itemBuilder: (context, i) => _row(state, i),
            ),
          ),
      ],
    );
  }

  List<Widget> _fractalSlivers(WhatsNewsState s) {
    final f = s.fractalStatus;
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                f.source.isEmpty ? 'whats-news fractal_scan (SPEC 25/27)' : f.source,
                style: const TextStyle(color: DeskColors.text, fontSize: 13, height: 1.4),
              ),
              if (f.reason.isNotEmpty) ...[
                const SizedBox(height: 6),
                Text(
                  f.reason,
                  style: const TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35),
                ),
              ],
              const SizedBox(height: 12),
              const Text(
                'Symbol · D 65d · D 130d · move 65d · move 130d · read',
                style: TextStyle(color: DeskColors.dim, fontSize: 11),
              ),
              const SizedBox(height: 8),
              if (f.rows.isEmpty)
                const Text(
                  'No Fractal rows. Seed a sleeve / Core 50 and Fetch Yahoo. Null D is a failed window — not invented.',
                  style: TextStyle(color: DeskColors.muted, fontSize: 13, height: 1.4),
                )
              else
                for (final row in f.rows)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: GestureDetector(
                      onTap: () => onOpenChart(row.symbol),
                      child: Text(
                        [
                          row.symbol,
                          row.d65d?.toStringAsFixed(2) ?? '—',
                          row.d130d?.toStringAsFixed(2) ?? '—',
                          row.move65d?.toStringAsFixed(1) ?? '—',
                          row.move130d?.toStringAsFixed(1) ?? '—',
                          row.read.isEmpty ? '—' : row.read,
                          if (row.tags.isNotEmpty) row.tags.join(','),
                        ].join(' · '),
                        style: TextStyle(
                          color: row.isFragile ? const Color(0xFFFECACA) : DeskColors.text,
                          fontSize: 13,
                          fontWeight: row.isFragile ? FontWeight.w700 : FontWeight.w400,
                        ),
                      ),
                    ),
                  ),
            ],
          ),
        ),
      ),
    ];
  }

  List<Widget> _finvizSlivers(WhatsNewsState s) {
    final scr = s.finvizScreener;
    final q = s.finvizQuote;
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  for (final e in const [
                    ('qulla_momentum', 'Qulla / mom'),
                    ('near_high', 'Near high'),
                    ('vol_surge', 'RVOL'),
                    ('new_high', 'New high'),
                    ('eps_growth', 'EPS'),
                  ])
                    _ModeChip(
                      label: e.$2,
                      on: s.finvizPreset == e.$1,
                      onTap: () => s.setFinvizPreset(e.$1),
                    ),
                ],
              ),
              const SizedBox(height: 8),
              Text(
                scr.reason.isEmpty
                    ? 'Public Finviz HTML. Empty when blocked — not invented tickers.'
                    : scr.reason,
                style: const TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35),
              ),
              const SizedBox(height: 10),
              if (scr.rows.isEmpty)
                const Text(
                  'No Finviz rows. Enable fetch in Settings, or the host was blocked.',
                  style: TextStyle(color: DeskColors.muted, fontSize: 13, height: 1.4),
                )
              else
                for (final row in scr.rows)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: GestureDetector(
                      onTap: () {
                        s.loadFinvizQuote(row.symbol);
                        onOpenChart(row.symbol);
                      },
                      child: Text(
                        [
                          row.symbol,
                          if (row.company.isNotEmpty) row.company,
                          if (row.sector.isNotEmpty) row.sector,
                          if (row.price.isNotEmpty) row.price,
                          if (row.change.isNotEmpty) row.change,
                        ].join(' · '),
                        style: const TextStyle(color: DeskColors.text, fontSize: 13),
                      ),
                    ),
                  ),
              if (q.symbol.isNotEmpty) ...[
                const SizedBox(height: 14),
                Text(
                  q.ready
                      ? '${q.symbol} ${q.name} · ${q.sector} · ${q.industry}'
                      : (q.reason.isEmpty ? 'No quote' : q.reason),
                  style: const TextStyle(color: DeskColors.accentBright, fontSize: 12),
                ),
                if (q.ready)
                  Text(
                    [
                      if (q.snapshot['pe'] != null) 'P/E ${q.snapshot['pe']}',
                      if (q.snapshot['rsi_14'] != null) 'RSI ${q.snapshot['rsi_14']}',
                      if (q.snapshot['perf_week'] != null) 'W ${q.snapshot['perf_week']}',
                      if (q.snapshot['short_float'] != null) 'short ${q.snapshot['short_float']}',
                    ].join(' · '),
                    style: const TextStyle(color: DeskColors.muted, fontSize: 12),
                  ),
              ],
            ],
          ),
        ),
      ),
    ];
  }

  List<Widget> _hmmSlivers(WhatsNewsState s) {
    final h = s.hmmRegime;
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'research label, not edge. SPY Gaussian HMM on stored daily log returns. Desk inherits SPY. Occupancy is not a win rate. Do not buy a regime flip.',
                style: TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 6,
                children: [
                  _ModeChip(label: '2-state', on: s.hmmStates == 2, onTap: () => s.setHmmStates(2)),
                  _ModeChip(label: '3-state', on: s.hmmStates == 3, onTap: () => s.setHmmStates(3)),
                  _ModeChip(label: 'Flip', on: s.hmmView == 'flip', onTap: () => s.setHmmView(s.hmmView == 'flip' ? 'all' : 'flip')),
                  _ModeChip(label: 'High-vol', on: s.hmmView == 'highvol', onTap: () => s.setHmmView(s.hmmView == 'highvol' ? 'all' : 'highvol')),
                  for (final st in h.states)
                    _ModeChip(
                      label: 'SPY=${st.label}',
                      on: s.hmmStateFilter == st.label,
                      onTap: () => s.setHmmStateFilter(st.label),
                    ),
                ],
              ),
              const SizedBox(height: 10),
              Text(
                h.available
                    ? 'SPY ${h.currentLabel.isEmpty ? '—' : h.currentLabel} · as-of ${h.asOf.isEmpty ? '—' : h.asOf}'
                    : (h.reason.isEmpty ? h.note : h.reason),
                style: const TextStyle(color: DeskColors.text, fontSize: 13),
              ),
              const SizedBox(height: 8),
              for (final st in h.states)
                Padding(
                  padding: const EdgeInsets.only(bottom: 4),
                  child: Text(
                    '${st.label} · mean ${st.mean ?? '—'} · σ ${st.vol ?? '—'} · '
                    'occ ${st.occupancy == null ? '—' : '${(st.occupancy! * 100).toStringAsFixed(0)}% of window (not a win rate)'}',
                    style: const TextStyle(color: DeskColors.muted, fontSize: 12),
                  ),
                ),
              const SizedBox(height: 8),
              if (h.rows.isEmpty)
                const Text(
                  'No HMM rows. Fetch Yahoo for SPY (~2y daily). research label, not edge.',
                  style: TextStyle(color: DeskColors.muted, fontSize: 13, height: 1.4),
                )
              else
                for (final row in h.rows)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: GestureDetector(
                      onTap: () => onOpenChart(row.symbol),
                      child: Text(
                        [
                          row.symbol,
                          row.inherited ? 'inherit SPY' : 'SPY fit',
                          row.spyState.isEmpty ? '—' : row.spyState,
                          if (row.spyProb != null) '${(row.spyProb! * 100).toStringAsFixed(0)}%',
                          row.note,
                        ].join(' · '),
                        style: const TextStyle(color: DeskColors.text, fontSize: 13),
                      ),
                    ),
                  ),
            ],
          ),
        ),
      ),
    ];
  }

  List<Widget> _comboSlivers(WhatsNewsState s) {
    final c = s.comboScan;
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                c.note.isEmpty
                    ? 'AND of real flags only: FRAGILE + inherited SPY HMM + EP/VOL_SURGE. research label, not edge.'
                    : c.note,
                style: const TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35),
              ),
              const SizedBox(height: 10),
              if (c.rows.isEmpty)
                Text(
                  c.reason.isEmpty
                      ? 'No combo hits. Empty is a missed real flag — not invented.'
                      : c.reason,
                  style: const TextStyle(color: DeskColors.muted, fontSize: 13, height: 1.4),
                )
              else
                for (final row in c.rows)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 6),
                    child: GestureDetector(
                      onTap: () => onOpenChart(row.symbol),
                      child: Text(
                        [
                          row.symbol,
                          if (row.spyState.isNotEmpty) row.spyState,
                          if (row.fragile) 'FRAGILE',
                          if (row.setups.isNotEmpty) row.setups.join(','),
                          row.note,
                        ].join(' · '),
                        style: const TextStyle(color: DeskColors.text, fontSize: 13),
                      ),
                    ),
                  ),
            ],
          ),
        ),
      ),
    ];
  }

  List<Widget> _edgesSlivers(WhatsNewsState s) {
    final board = s.edgesBoard;
    final children = <Widget>[
      if (board.regime.ready)
        Text(
          '${board.regime.label} · VIX ${board.regime.vix?.toStringAsFixed(1) ?? '—'}',
          style: const TextStyle(color: DeskColors.accentBright, fontSize: 13, fontWeight: FontWeight.w700),
        )
      else
        Text(
          board.regime.note.isEmpty ? 'VIX regime omitted — no stored bars.' : board.regime.note,
          style: const TextStyle(color: DeskColors.muted, fontSize: 12),
        ),
      const SizedBox(height: 8),
      Text(
        board.online.isEmpty
            ? 'No live tags yet — fetch sleeve bars.'
            : 'Online: ${board.online.join(' · ')}',
        style: const TextStyle(color: DeskColors.text, fontSize: 13),
      ),
      const SizedBox(height: 4),
      Text(board.note, style: const TextStyle(color: DeskColors.dim, fontSize: 11)),
      const SizedBox(height: 10),
    ];
    final filtered = s.filteredEdgeRows;
    if (s.edgeTag.isEmpty) {
      for (final sec in board.sections) {
        children.add(Text(
          sec.label,
          style: const TextStyle(color: DeskColors.muted, fontSize: 12, fontWeight: FontWeight.w700),
        ));
        children.add(const SizedBox(height: 4));
        for (final row in sec.rows) {
          children.add(_EdgeTile(row: row, onOpen: onOpenChart));
        }
        children.add(const SizedBox(height: 10));
      }
    } else {
      children.add(Text(
        'Tag: ${s.edgeTag}',
        style: const TextStyle(color: DeskColors.muted, fontSize: 12, fontWeight: FontWeight.w700),
      ));
      children.add(const SizedBox(height: 4));
      for (final row in filtered) {
        children.add(_EdgeTile(row: row, onOpen: onOpenChart));
      }
      children.add(const SizedBox(height: 10));
    }
    if (board.setupBuckets.isNotEmpty) {
      children.add(const Text(
        'Stock-level setups (desk)',
        style: TextStyle(color: DeskColors.muted, fontSize: 12, fontWeight: FontWeight.w700),
      ));
      board.setupBuckets.forEach((id, names) {
        children.add(Padding(
          padding: const EdgeInsets.only(top: 6, bottom: 2),
          child: Text(id, style: const TextStyle(color: DeskColors.dim, fontSize: 11)),
        ));
        children.add(Wrap(
          spacing: 6,
          runSpacing: 6,
          children: [
            if (names.isEmpty)
              const Text('none', style: TextStyle(color: DeskColors.dim, fontSize: 12))
            else
              for (final n in names)
                GestureDetector(
                  onTap: () => onOpenChart(n),
                  child: Text(n, style: const TextStyle(color: DeskColors.accentBright, fontSize: 13, fontWeight: FontWeight.w600)),
                ),
          ],
        ));
      });
    }
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: children,
          ),
        ),
      ),
    ];
  }

  List<Widget> _emptyNote(String msg) => [
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
            child: Text(msg, style: const TextStyle(color: DeskColors.muted, height: 1.4)),
          ),
        ),
      ];

  List<Widget> _howto(String text) => [
        if (text.isNotEmpty)
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(16, 8, 16, 16),
              child: Text(
                'HOW TO READ\n$text',
                style: const TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35),
              ),
            ),
          ),
      ];

  Widget _nameChip(String symbol, String tag, {String? metric}) {
    return GestureDetector(
      onTap: () => onOpenChart(symbol),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(
          children: [
            Text(symbol, style: const TextStyle(color: DeskColors.accentBright, fontWeight: FontWeight.w700)),
            if (metric != null && metric.isNotEmpty) ...[
              const SizedBox(width: 8),
              Text(metric, style: const TextStyle(color: DeskColors.text, fontSize: 12)),
            ],
            const Spacer(),
            if (tag.isNotEmpty)
              Text(tag, style: const TextStyle(color: DeskColors.dim, fontSize: 11)),
          ],
        ),
      ),
    );
  }

  List<Widget> _commandSlivers(WhatsNewsState s) {
    final b = s.engineCommand;
    if (!b.ready) {
      return _emptyNote(b.message.isEmpty ? 'Empty command — seed a sleeve and Fetch Yahoo.' : b.message);
    }
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'OPPORTUNITY ${b.counts['OPPORTUNITY'] ?? 0} · WATCH ${b.counts['WATCH'] ?? 0} · NO TRADE ${b.counts['NO TRADE'] ?? 0}',
                style: const TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700),
              ),
              const SizedBox(height: 8),
              const Text('Opportunity', style: TextStyle(color: DeskColors.muted, fontSize: 12)),
              Wrap(
                spacing: 8,
                children: [
                  for (final n in b.opportunity)
                    GestureDetector(
                      onTap: () => onOpenChart(n),
                      child: Text(n, style: const TextStyle(color: DeskColors.accentBright, fontWeight: FontWeight.w700)),
                    ),
                  if (b.opportunity.isEmpty)
                    const Text('none', style: TextStyle(color: DeskColors.dim, fontSize: 12)),
                ],
              ),
              const SizedBox(height: 8),
              const Text('Pullback-in-uptrend', style: TextStyle(color: DeskColors.muted, fontSize: 12)),
              Wrap(
                spacing: 8,
                children: [
                  for (final n in b.pullbacks)
                    GestureDetector(
                      onTap: () => onOpenChart(n),
                      child: Text(n, style: const TextStyle(color: DeskColors.accentBright, fontWeight: FontWeight.w700)),
                    ),
                  if (b.pullbacks.isEmpty)
                    const Text('none', style: TextStyle(color: DeskColors.dim, fontSize: 12)),
                ],
              ),
            ],
          ),
        ),
      ),
      ..._howto(b.formulas['engine'] ?? b.howto),
    ];
  }

  List<Widget> _setupEngineSlivers(WhatsNewsState s) {
    final b = s.engineBoard;
    if (b.rows.isEmpty) {
      return _emptyNote(b.message.isEmpty ? 'Empty ENGINE — no stored daily bars.' : b.message);
    }
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Text(
            b.note.isEmpty
                ? 'WATCH | FORMING | TRIGGERED | ACCEPTED | OPPORTUNITY | DORMANT | EXTENDED | NO TRADE. D is SPEC 25/27 only.'
                : b.note,
            style: const TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35),
          ),
        ),
      ),
      SliverPadding(
        padding: const EdgeInsets.only(bottom: 8),
        sliver: SliverList.separated(
          itemCount: b.rows.length,
          separatorBuilder: (_, _) => const Padding(
            padding: EdgeInsets.symmetric(horizontal: 16),
            child: ColoredBox(color: DeskColors.border, child: SizedBox(height: 0.5)),
          ),
          itemBuilder: (context, i) {
            final r = b.rows[i];
            return GestureDetector(
              onTap: () => onOpenChart(r.symbol),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Text(r.symbol, style: const TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700, fontSize: 16)),
                        const Spacer(),
                        Text(r.engine, style: const TextStyle(color: DeskColors.accentBright, fontSize: 11, fontWeight: FontWeight.w700)),
                      ],
                    ),
                    const SizedBox(height: 4),
                    Text(
                      r.takeaway.isEmpty ? '—' : r.takeaway,
                      style: TextStyle(
                        color: r.sentiment.contains('LONG')
                            ? DeskColors.green
                            : r.sentiment.contains('SHORT')
                                ? DeskColors.red
                                : DeskColors.muted,
                        fontSize: 12,
                        height: 1.3,
                      ),
                    ),
                    Text(
                      [
                        if (r.vcp.isNotEmpty) r.vcp,
                        if (r.tmsZone.isNotEmpty) r.tmsZone,
                        if (r.impulse.isNotEmpty) r.impulse,
                        if (r.dw.isNotEmpty) r.dw,
                        if (r.str != null) 'Str ${r.str}',
                        if (r.tmacStar != null) 'TMAC* ${r.tmacStar}',
                      ].join(' · '),
                      style: const TextStyle(color: DeskColors.dim, fontSize: 11),
                    ),
                  ],
                ),
              ),
            );
          },
        ),
      ),
      ..._howto(b.formulas['engine'] ?? ''),
    ];
  }

  List<Widget> _patternSlivers(WhatsNewsState s) {
    final b = s.patternBoard;
    if (!b.ready) {
      return [
        ..._emptyNote(b.message.isEmpty ? 'Empty pattern scanner — no 3M/1Y extremes.' : b.message),
        ..._howto(b.howto),
      ];
    }
    Widget col(String title, List<EngineNamed> rows) => Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: const TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700, fontSize: 13)),
              if (rows.isEmpty)
                const Text('none', style: TextStyle(color: DeskColors.dim, fontSize: 12))
              else
                for (final r in rows) _nameChip(r.symbol, r.tag),
            ],
          ),
        );
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              col('Daily Breakouts (${b.dailyCounts['Breakout'] ?? 0})', b.daily['Breakout'] ?? const []),
              col('Daily From Bottom (${b.dailyCounts['From Bottom'] ?? 0})', b.daily['From Bottom'] ?? const []),
              col('Daily Breakdowns (${b.dailyCounts['Breakdown'] ?? 0})', b.daily['Breakdown'] ?? const []),
              col('Daily From Top (${b.dailyCounts['From Top'] ?? 0})', b.daily['From Top'] ?? const []),
              col('Weekly Breakouts (${b.weeklyCounts['Breakout'] ?? 0})', b.weekly['Breakout'] ?? const []),
              col('Weekly From Bottom (${b.weeklyCounts['From Bottom'] ?? 0})', b.weekly['From Bottom'] ?? const []),
              col('Weekly Breakdowns (${b.weeklyCounts['Breakdown'] ?? 0})', b.weekly['Breakdown'] ?? const []),
              col('Weekly From Top (${b.weeklyCounts['From Top'] ?? 0})', b.weekly['From Top'] ?? const []),
            ],
          ),
        ),
      ),
      ..._howto(b.howto),
    ];
  }

  List<Widget> _rsicSlivers(WhatsNewsState s) {
    final b = s.rsiCounter;
    if (!b.ready) {
      return [
        ..._emptyNote(b.message.isEmpty ? 'Empty RSI-C — need ≥24 stored closes.' : b.message),
        ..._howto(b.howto),
      ];
    }
    Widget bucket(String title, List<EngineNamed> rows) => Padding(
          padding: const EdgeInsets.only(bottom: 10),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: const TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700, fontSize: 13)),
              if (rows.isEmpty)
                const Text('none', style: TextStyle(color: DeskColors.dim, fontSize: 12))
              else
                for (final r in rows)
                  _nameChip(
                    r.symbol,
                    r.state.isEmpty ? r.tag : r.state,
                    metric: r.avgRsi == null ? null : 'avg ${r.avgRsi!.toStringAsFixed(1)}',
                  ),
            ],
          ),
        );
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('CONTROLS RSI n=${b.rsiN}  Δ lag=${b.lag}', style: const TextStyle(color: DeskColors.muted, fontSize: 12)),
              const SizedBox(height: 8),
              const Text('Daily LEFT', style: TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700)),
              bucket('OVERSOLD', b.daily['oversold'] ?? const []),
              bucket('OVERBOUGHT', b.daily['overbought'] ?? const []),
              bucket('TRENDING HIGHER', b.daily['trend_up'] ?? const []),
              bucket('TRENDING LOWER', b.daily['trend_dn'] ?? const []),
              const Text('Weekly RIGHT', style: TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700)),
              bucket('OVERSOLD W', b.weekly['oversold'] ?? const []),
              bucket('OVERBOUGHT W', b.weekly['overbought'] ?? const []),
              bucket('TRENDING HIGHER W', b.weekly['trend_up'] ?? const []),
              bucket('TRENDING LOWER W', b.weekly['trend_dn'] ?? const []),
              bucket('Accelerating', b.accelerating),
              bucket('Fading', b.fading),
              bucket('Sector RSI', b.sectors),
              bucket('Pullback-in-uptrend', b.pullbacks),
            ],
          ),
        ),
      ),
      ..._howto(b.howto),
    ];
  }

  List<Widget> _warningsSlivers(WhatsNewsState s) {
    final b = s.warningsBoard;
    if (!b.ready) {
      return [
        ..._emptyNote(
          b.message.isEmpty
              ? 'Empty warnings — no Pattern / VCP / RSI-C hits on stored bars.'
              : b.message,
        ),
        ..._howto(b.howto),
      ];
    }
    Widget col(String title, List<WarningHit> rows) {
      if (rows.isEmpty) return const SizedBox.shrink();
      return Padding(
        padding: const EdgeInsets.only(bottom: 4),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              '$title (${rows.length})',
              style: const TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700, fontSize: 11),
            ),
            for (final r in rows)
              _nameChip(
                r.symbol,
                [
                  if (r.label.isNotEmpty) r.label,
                  if (r.patternD.isNotEmpty) r.patternD,
                  if (r.vcp.isNotEmpty) r.vcp,
                  if (r.rsiC.isNotEmpty) r.rsiC,
                  if (r.str != null) 'Str ${r.str}',
                ].where((e) => e.isNotEmpty).join(' · '),
              ),
          ],
        ),
      );
    }
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Takeaways · breaking up/down · coiled · stretch. Empty buckets omitted.',
                style: TextStyle(color: DeskColors.muted, fontSize: 11),
              ),
              const SizedBox(height: 6),
              col('Takeaways', b.takeaways),
              col('Breaking up D', b.dailyBreakout),
              col('Breaking down D', b.dailyBreakdown),
              col('VCP Coiled', b.coiled),
              col('VCP Tightening', b.tightening),
              col('Strongest', b.strongest),
              col('Stretched', b.stretched),
              col('Compressed', b.compressed),
              col('From Bottom D', b.dailyFromBottom),
              col('From Top D', b.dailyFromTop),
              col('Breakouts W', b.weeklyBreakout),
              col('Breakdowns W', b.weeklyBreakdown),
              col('RSI-C D OS', b.dailyOs),
              col('RSI-C D OB', b.dailyOb),
              col('D+W ↑', b.dwUp),
              col('D+W ↓', b.dwDn),
            ],
          ),
        ),
      ),
      ..._howto(b.howto),
    ];
  }

  List<Widget> _stretchSlivers(WhatsNewsState s) {
    final b = s.stretchBoard;
    if (!b.ready) {
      return [
        ..._emptyNote(b.message.isEmpty ? 'Empty stretch board — need ≥56 daily bars for Str.' : b.message),
        ..._howto(b.howto),
      ];
    }
    Widget col(String title, List<EngineNamed> rows) => Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: const TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700, fontSize: 13)),
              if (rows.isEmpty)
                const Text('none', style: TextStyle(color: DeskColors.dim, fontSize: 12))
              else
                for (final r in rows)
                  _nameChip(r.symbol, r.tag, metric: r.metric == null ? null : r.metric!.toStringAsFixed(1)),
            ],
          ),
        );
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              col('Strongest breakouts', b.strongest),
              col('Breakdowns', b.breakdowns),
              col('Most stretched (ADMA)', b.stretched),
              col('Most compressed (ADMA)', b.compressed),
            ],
          ),
        ),
      ),
      ..._howto(b.howto),
    ];
  }

  List<Widget> _sigmaSlivers(WhatsNewsState s) {
    final b = s.sigmaBoard;
    if (b.rows.isEmpty) {
      return _emptyNote(b.message.isEmpty ? 'Empty sigma grid — no stored closes.' : b.message);
    }
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Text(
            b.note.isEmpty ? 'σ = move / (trailing daily σ × √horizon). Yahoo/SQLite only.' : b.note,
            style: const TextStyle(color: DeskColors.muted, fontSize: 12),
          ),
        ),
      ),
      SliverPadding(
        padding: const EdgeInsets.only(bottom: 24),
        sliver: SliverList.separated(
          itemCount: b.rows.length,
          separatorBuilder: (_, _) => const Padding(
            padding: EdgeInsets.symmetric(horizontal: 16),
            child: ColoredBox(color: DeskColors.border, child: SizedBox(height: 0.5)),
          ),
          itemBuilder: (context, i) {
            final r = b.rows[i];
            final sym = '${r['symbol'] ?? ''}'.toUpperCase();
            return GestureDetector(
              onTap: () => onOpenChart(sym),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(sym, style: const TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700, fontSize: 16)),
                    Text(
                      '${r['takeaway'] ?? '—'}',
                      style: const TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.3),
                    ),
                  ],
                ),
              ),
            );
          },
        ),
      ),
    ];
  }

  List<Widget> _mapsSlivers(WhatsNewsState s) {
    final m = s.engineMaps;
    if (!m.ready) {
      return [
        ..._emptyNote(m.message.isEmpty ? 'Empty maps — seed a sleeve and Fetch Yahoo.' : m.message),
        ..._howto(m.howto),
      ];
    }
    Widget pts(String title, List<MapPoint> rows) => Padding(
          padding: const EdgeInsets.only(bottom: 12),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(title, style: const TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700, fontSize: 13)),
              if (rows.isEmpty)
                const Text('none', style: TextStyle(color: DeskColors.dim, fontSize: 12))
              else
                for (final p in rows)
                  _nameChip(
                    p.symbol,
                    [p.assetClass, if (p.tag.isNotEmpty) p.tag, if (p.arrow.isNotEmpty) p.arrow].join(' · '),
                    metric: (p.x == null || p.y == null)
                        ? null
                        : '${p.x!.toStringAsFixed(1)}, ${p.y!.toStringAsFixed(1)}',
                  ),
            ],
          ),
        );
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                m.tmacNote.isEmpty ? 'TMAC* heat proxy — never branded TMAC' : m.tmacNote,
                style: const TextStyle(color: DeskColors.muted, fontSize: 12),
              ),
              if (m.spyLabel.isNotEmpty)
                Text('SPY strip ${m.spyLabel} — research label, not edge.',
                    style: const TextStyle(color: DeskColors.yellow, fontSize: 12)),
              const SizedBox(height: 8),
              pts('Scanner', [
                for (final r in m.scanner)
                  MapPoint(symbol: r.symbol, tag: r.tag, assetClass: r.state),
              ]),
              pts('Rotation RSI(14) vs 1w σ', m.rotation),
              pts('Coil 12w/26w vs 13w pos', m.coil),
              pts('Fractal × TD (D only)', m.fractalTd),
              pts('TMS-W solid', m.tmsWeekly),
              pts('TMS-D hollow', m.tmsDaily),
              pts('Top 12M', [
                for (final r in m.top12m) MapPoint(symbol: r.symbol, tag: r.note),
              ]),
              pts('Bottom 12M', [
                for (final r in m.bottom12m) MapPoint(symbol: r.symbol, tag: r.note),
              ]),
            ],
          ),
        ),
      ),
      ..._howto('${m.howto}\n${m.tdNote}'.trim()),
    ];
  }

  /// Flutter path for Market Moves: same GET /api/market-moves as the web grid.
  ///
  /// Customize (web first): GET /api/boards/registry or payload.columns[].
  /// Persist SharedPreferences key `whats-news-desk-prefs` field `boardColumns`
  /// `{ market_moves: { order: [...], hidden: [...] }, engine_setup: {...} }`
  /// then render only visible ids in this sliver. Locked `name` / `symbol` stay on.
  /// Do not invent PX / z when a measure is hidden.
  List<Widget> _movesSlivers(WhatsNewsState s) {
    final b = s.marketMoves;
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Text(
            [
              if (b.asofEt.isNotEmpty) b.asofEt,
              if (b.asof != null) 'session ${b.asof}',
              b.legend.isEmpty
                  ? 'shade=|z| intensity · • = |z|≥2 · daily z vs ~30d stdev · 14D: 14-day move in 14-day sigmas'
                  : b.legend,
              b.source.isEmpty ? 'Yahoo/stored OHLCV — not CNBC/Finviz as SoT.' : b.source,
            ].join('\n'),
            style: const TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35),
          ),
        ),
      ),
      for (final g in b.groups)
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(g.label, style: const TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700, fontSize: 13)),
                const SizedBox(height: 4),
                for (final r in g.rows)
                  Padding(
                    padding: const EdgeInsets.symmetric(vertical: 2),
                    child: Row(
                      children: [
                        SizedBox(
                          width: 72,
                          child: Text(r.name, style: const TextStyle(color: DeskColors.text, fontSize: 12, fontWeight: FontWeight.w600)),
                        ),
                        Expanded(
                          child: Text(
                            r.ready && r.px != null ? r.px!.toStringAsFixed(2) : '—',
                            style: const TextStyle(color: DeskColors.muted, fontSize: 12, fontFeatures: []),
                            textAlign: TextAlign.right,
                          ),
                        ),
                        Expanded(
                          child: Text(
                            r.dayPct == null
                                ? '—'
                                : '${r.dayPct! >= 0 ? '+' : ''}${r.dayPct!.toStringAsFixed(1)}',
                            style: TextStyle(
                              color: r.dayPct == null
                                  ? DeskColors.muted
                                  : (r.dayPct! >= 0 ? DeskColors.green : DeskColors.red),
                              fontSize: 12,
                            ),
                            textAlign: TextAlign.right,
                          ),
                        ),
                        Expanded(
                          child: Text(
                            r.z == null ? '—' : '${r.extreme ? '• ' : ''}${r.z! >= 0 ? '+' : ''}${r.z!.toStringAsFixed(1)}',
                            style: TextStyle(
                              color: r.z == null
                                  ? DeskColors.muted
                                  : (r.z! >= 0 ? DeskColors.green : DeskColors.red),
                              fontSize: 12,
                            ),
                            textAlign: TextAlign.right,
                          ),
                        ),
                        Expanded(
                          child: Text(
                            r.z14 == null ? '—' : '${r.z14! >= 0 ? '+' : ''}${r.z14!.toStringAsFixed(1)}',
                            style: TextStyle(
                              color: r.z14 == null
                                  ? DeskColors.muted
                                  : (r.z14! >= 0 ? DeskColors.green : DeskColors.red),
                              fontSize: 12,
                            ),
                            textAlign: TextAlign.right,
                          ),
                        ),
                      ],
                    ),
                  ),
              ],
            ),
          ),
        ),
    ];
  }

  List<Widget> _packSlivers(WhatsNewsState s) {
    final pack = s.scanPack;
    final note = s.scanMode == 'oneil'
        ? pack.oneilNote
        : s.scanMode == 'vcp'
            ? pack.vcpNote
            : pack.note;
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Text(
            note.isEmpty
                ? 'MA / RSI / Breakout from stored daily bars. Style chips are filters — O\'Neil is price/RS only. VCP is an honest proxy, not certified VCP.'
                : note,
            style: const TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35),
          ),
        ),
      ),
      if (pack.rows.isEmpty)
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
            child: Text(
              pack.message.isEmpty
                  ? 'No pack hits from stored bars. Empty is honest — not a fake print.'
                  : pack.message,
              style: const TextStyle(color: DeskColors.muted, height: 1.4),
            ),
          ),
        )
      else
        SliverPadding(
          padding: const EdgeInsets.only(bottom: 24),
          sliver: SliverList.separated(
            itemCount: pack.rows.length,
            separatorBuilder: (_, _) => const Padding(
              padding: EdgeInsets.symmetric(horizontal: 16),
              child: ColoredBox(color: DeskColors.border, child: SizedBox(height: 0.5)),
            ),
            itemBuilder: (context, i) => _PackTile(row: pack.rows[i], onOpen: onOpenChart),
          ),
        ),
    ];
  }

  bool _rowsEmpty(WhatsNewsState s) {
    switch (s.scanMode) {
      case 'metrics':
        return s.metricScan.isEmpty;
      case 'setups':
        return s.setupScan.isEmpty;
      case 'qulla':
        return s.qullaRows.isEmpty;
      case 'ma':
      case 'rsi':
      case 'breakout':
      case 'oneil':
      case 'vcp':
        return s.scanPack.rows.isEmpty;
      default:
        return s.trendScan.isEmpty;
    }
  }

  int _count(WhatsNewsState s) {
    switch (s.scanMode) {
      case 'metrics':
        return s.metricScan.length;
      case 'setups':
        return s.setupScan.length;
      case 'qulla':
        return s.qullaRows.length;
      default:
        return s.trendScan.length;
    }
  }

  Widget _row(WhatsNewsState s, int i) {
    switch (s.scanMode) {
      case 'metrics':
        return _MetricTile(row: s.metricScan[i], onOpen: onOpenChart);
      case 'setups':
        return _SetupTile(row: s.setupScan[i], onOpen: onOpenChart);
      case 'qulla':
        return _SetupTile(row: s.qullaRows[i], onOpen: onOpenChart);
      default:
        return _TrendTile(row: s.trendScan[i], onOpen: onOpenChart);
    }
  }
}

class _ModeChip extends StatelessWidget {
  const _ModeChip({required this.label, required this.on, required this.onTap});
  final String label;
  final bool on;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 3),
        decoration: BoxDecoration(
          color: on ? DeskColors.accent.withValues(alpha: 0.2) : DeskColors.card,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: on ? DeskColors.accent : DeskColors.border),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: on ? DeskColors.accentBright : DeskColors.muted,
            fontSize: 12,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

class _EdgeTile extends StatelessWidget {
  const _EdgeTile({required this.row, required this.onOpen});
  final EdgeInstrument row;
  final ValueChanged<String> onOpen;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: row.ready ? () => onOpen(row.symbol) : null,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: 6),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  row.symbol,
                  style: TextStyle(
                    color: row.ready ? DeskColors.text : DeskColors.dim,
                    fontWeight: FontWeight.w700,
                    fontSize: 15,
                  ),
                ),
                const Spacer(),
                if (row.ready && row.dayPct != null)
                  Text(
                    '${row.dayPct! >= 0 ? '+' : ''}${row.dayPct!.toStringAsFixed(1)}%',
                    style: TextStyle(
                      color: row.dayPct! >= 0 ? DeskColors.green : DeskColors.red,
                      fontSize: 12,
                    ),
                  ),
              ],
            ),
            Text(
              row.ready
                  ? [
                      if (row.dRsi14 != null) 'dRSI ${row.dRsi14!.toStringAsFixed(0)}',
                      if (row.wRsi14 != null) 'wRSI ${row.wRsi14!.toStringAsFixed(0)}',
                      if (row.vs50d != null) 'vs50 ${row.vs50d!.toStringAsFixed(1)}%',
                      if (row.vs200d != null) 'vs200 ${row.vs200d!.toStringAsFixed(1)}%',
                      if (row.slope200 != null) row.slope200!,
                      ...row.tags,
                    ].join(' · ')
                  : 'no bars',
              style: const TextStyle(color: DeskColors.muted, fontSize: 12),
            ),
          ],
        ),
      ),
    );
  }
}

class _TrendTile extends StatelessWidget {
  const _TrendTile({required this.row, required this.onOpen});

  final TrendScanRow row;
  final ValueChanged<String> onOpen;

  @override
  Widget build(BuildContext context) {
    final err = row.error;
    return GestureDetector(
      onTap: () => onOpen(row.symbol),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  row.symbol,
                  style: const TextStyle(
                    color: DeskColors.text,
                    fontWeight: FontWeight.w700,
                    fontSize: 16,
                  ),
                ),
                const SizedBox(width: 8),
                if (row.price != null)
                  Text(
                    row.price!.toStringAsFixed(2),
                    style: const TextStyle(color: DeskColors.muted, fontSize: 14),
                  ),
                const Spacer(),
                if (row.signal != null)
                  Text(
                    'sig ${row.signal}',
                    style: const TextStyle(
                      color: DeskColors.accentBright,
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 4),
            if (err != null)
              Text(err, style: const TextStyle(color: DeskColors.red, fontSize: 12))
            else
              Text(
                [
                  if (row.rsi != null) 'RSI ${row.rsi!.toStringAsFixed(1)}',
                  if (row.kama10Pct != null) 'K10 ${row.kama10Pct!.toStringAsFixed(1)}%',
                  if (row.kama20Pct != null) 'K20 ${row.kama20Pct!.toStringAsFixed(1)}%',
                  if (row.kama50Pct != null) 'K50 ${row.kama50Pct!.toStringAsFixed(1)}%',
                  if (row.rr != null) 'R/R ${row.rr!.toStringAsFixed(2)}',
                ].join(' · '),
                style: const TextStyle(color: DeskColors.muted, fontSize: 12),
              ),
          ],
        ),
      ),
    );
  }
}

class _MetricTile extends StatelessWidget {
  const _MetricTile({required this.row, required this.onOpen});

  final ScannerRow row;
  final ValueChanged<String> onOpen;

  @override
  Widget build(BuildContext context) {
    final d = row.daily;
    final chg = row.chg;
    final up = (chg ?? 0) >= 0;
    return GestureDetector(
      onTap: () => onOpen(row.symbol),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  row.symbol,
                  style: const TextStyle(
                    color: DeskColors.text,
                    fontWeight: FontWeight.w700,
                    fontSize: 16,
                  ),
                ),
                const SizedBox(width: 8),
                if (row.price != null)
                  Text(
                    row.price!.toStringAsFixed(2),
                    style: const TextStyle(color: DeskColors.muted, fontSize: 14),
                  ),
                const Spacer(),
                if (chg != null)
                  Text(
                    '${up ? '+' : ''}${chg.toStringAsFixed(2)}%',
                    style: TextStyle(
                      color: up ? DeskColors.green : DeskColors.red,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 4),
            if (row.error != null)
              Text(row.error!, style: const TextStyle(color: DeskColors.red, fontSize: 12))
            else
              Text(
                [
                  if (d.rsi14 != null) 'RSI14 ${d.rsi14!.toStringAsFixed(1)}',
                  if (d.atrPct != null) 'ATR% ${d.atrPct!.toStringAsFixed(2)}',
                  if (d.roc1m != null) 'ROC1m ${d.roc1m!.toStringAsFixed(1)}%',
                  if (d.distSma != null) 'vs SMA ${d.distSma!.toStringAsFixed(1)}%',
                  if (d.volRatio != null) 'vol ${d.volRatio!.toStringAsFixed(2)}',
                  if (d.trendScore != null) 'score ${d.trendScore!.toStringAsFixed(0)}',
                ].join(' · '),
                style: const TextStyle(color: DeskColors.muted, fontSize: 12),
              ),
          ],
        ),
      ),
    );
  }
}

class _SetupTile extends StatelessWidget {
  const _SetupTile({required this.row, required this.onOpen});

  final SetupScanRow row;
  final ValueChanged<String> onOpen;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => onOpen(row.symbol),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  row.symbol,
                  style: const TextStyle(
                    color: DeskColors.text,
                    fontWeight: FontWeight.w700,
                    fontSize: 16,
                  ),
                ),
                const SizedBox(width: 8),
                if (row.price != null)
                  Text(
                    row.price!.toStringAsFixed(2),
                    style: const TextStyle(color: DeskColors.muted, fontSize: 14),
                  ),
                const Spacer(),
                if (row.setupScore != null)
                  Text(
                    'score ${row.setupScore!.toStringAsFixed(0)}',
                    style: const TextStyle(
                      color: DeskColors.accentBright,
                      fontSize: 12,
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 4),
            if (row.error != null)
              Text(row.error!, style: const TextStyle(color: DeskColors.red, fontSize: 12))
            else
              Text(
                [
                  if (row.setups.isNotEmpty) row.setups.join(', '),
                  if (row.adrPct != null) 'ADR% ${row.adrPct!.toStringAsFixed(2)}',
                  if (row.tmacStar != null) 'TMAC* ${row.tmacStar}',
                  if (row.regime != null) row.regime!,
                ].join(' · '),
                style: const TextStyle(color: DeskColors.muted, fontSize: 12),
              ),
          ],
        ),
      ),
    );
  }
}

class _BreadthStrip extends StatelessWidget {
  const _BreadthStrip({required this.breadth, this.engineReady = false});
  final ScanBreadth breadth;
  final bool engineReady;

  @override
  Widget build(BuildContext context) {
    String pct(double? v) => v == null ? '—' : '${v.toStringAsFixed(1)}%';
    String ad(int? a, int? d) => (a == null && d == null) ? '—' : '${a ?? 0}/${d ?? 0}';
    Widget cell(String k, String v) => Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(k, style: const TextStyle(color: DeskColors.dim, fontSize: 10, letterSpacing: 0.4)),
              const SizedBox(height: 2),
              Text(v, style: const TextStyle(color: DeskColors.text, fontSize: 14, fontWeight: FontWeight.w700)),
            ],
          ),
        );
    return Container(
      padding: const EdgeInsets.fromLTRB(10, 8, 10, 8),
      decoration: BoxDecoration(
        color: DeskColors.card,
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: DeskColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              cell('% >SMA50', pct(breadth.pctAboveSma50)),
              cell('% >SMA200', pct(breadth.pctAboveSma200)),
              cell('A/D 1d', ad(breadth.adv1d, breadth.dec1d)),
              cell('A/D 5d', ad(breadth.adv5d, breadth.dec5d)),
            ],
          ),
          const SizedBox(height: 4),
          Text(
            breadth.ready
                ? (breadth.note.isEmpty ? 'Our Yahoo/SQLite universe — not a scraped Market Monitor.' : breadth.note)
                : (engineReady
                    ? 'ENGINE has hits from stored bars. Breadth dashes until the desk list is scored.'
                    : (breadth.message.contains('no stored bars') && engineReady
                        ? 'ENGINE has hits from stored bars.'
                        : (breadth.message.isEmpty ? 'Breadth not scored yet.' : breadth.message))),
            style: const TextStyle(color: DeskColors.muted, fontSize: 10, height: 1.3),
          ),
        ],
      ),
    );
  }
}

class _PackTile extends StatelessWidget {
  const _PackTile({required this.row, required this.onOpen});
  final ScanPackRow row;
  final ValueChanged<String> onOpen;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () => onOpen(row.symbol),
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Text(
                  row.symbol,
                  style: const TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700, fontSize: 16),
                ),
                const Spacer(),
                if (row.dayPct != null)
                  Text(
                    '${row.dayPct! >= 0 ? '+' : ''}${row.dayPct!.toStringAsFixed(1)}%',
                    style: TextStyle(
                      color: row.dayPct! >= 0 ? DeskColors.green : DeskColors.red,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
              ],
            ),
            const SizedBox(height: 4),
            Text(
              [
                if (row.vs50 != null) 'vs50 ${row.vs50!.toStringAsFixed(1)}%',
                if (row.rsi14 != null) 'RSI ${row.rsi14!.toStringAsFixed(1)}',
                if (row.dist52w != null) '52w ${row.dist52w!.toStringAsFixed(1)}%',
                if (row.volRatio != null) 'vol ${row.volRatio!.toStringAsFixed(2)}×',
                if (row.tags.isNotEmpty) row.tags.join(' '),
              ].join(' · '),
              style: const TextStyle(color: DeskColors.muted, fontSize: 12),
            ),
          ],
        ),
      ),
    );
  }
}
