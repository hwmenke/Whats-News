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
                  'Same Python scans as the web desk. Fractal is SPEC 25/27. HMM is a research label, not edge — SPY Gaussian, desk inherits. Finviz is public HTML only.',
                  style: TextStyle(color: DeskColors.muted, fontSize: 12),
                ),
                if (running)
                  const Padding(
                    padding: EdgeInsets.only(top: 6),
                    child: Text(
                      'S&P 500 archive fetch is running in the background.',
                      style: TextStyle(color: Color(0xFFEAB308), fontSize: 12),
                    ),
                  ),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    for (final e in const [
                      ('qulla', 'Qulla'),
                      ('edges', 'Edges'),
                      ('fractal', 'Fractal'),
                      ('finviz', 'Finviz'),
                      ('hmm', 'HMM'),
                      ('setups', 'Setups'),
                      ('trend', 'Trend'),
                      ('metrics', 'Metrics'),
                    ])
                      _ModeChip(
                        label: e.$2,
                        on: state.scanMode == e.$1,
                        onTap: () => state.setScanMode(e.$1),
                      ),
                  ],
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

  bool _rowsEmpty(WhatsNewsState s) {
    switch (s.scanMode) {
      case 'metrics':
        return s.metricScan.isEmpty;
      case 'setups':
        return s.setupScan.isEmpty;
      case 'qulla':
        return s.qullaRows.isEmpty;
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
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
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
