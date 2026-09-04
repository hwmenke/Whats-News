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
            onPressed: state.loadingScans ? null : state.loadScans,
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
                  'Watchlist only — same Python scans as Dash. No S&P 500 bulk fetch required.',
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
                CupertinoSlidingSegmentedControl<String>(
                  groupValue: state.scanMode,
                  children: const {
                    'trend': Padding(
                      padding: EdgeInsets.symmetric(horizontal: 8),
                      child: Text('Trend', style: TextStyle(fontSize: 13)),
                    ),
                    'metrics': Padding(
                      padding: EdgeInsets.symmetric(horizontal: 8),
                      child: Text('Metrics', style: TextStyle(fontSize: 13)),
                    ),
                    'setups': Padding(
                      padding: EdgeInsets.symmetric(horizontal: 8),
                      child: Text('Setups', style: TextStyle(fontSize: 13)),
                    ),
                  },
                  onValueChanged: (v) {
                    if (v != null) state.setScanMode(v);
                  },
                ),
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
        if (state.loadingScans && _rowsEmpty(state))
          const SliverFillRemaining(
            child: Center(child: CupertinoActivityIndicator()),
          )
        else if (_rowsEmpty(state))
          const SliverFillRemaining(
            hasScrollBody: false,
            child: Padding(
              padding: EdgeInsets.all(24),
              child: Text(
                'No scan rows yet.\n\nAdd tickers on Watchlist and Fetch from Yahoo so finance.db has bars. Then refresh here.',
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

  bool _rowsEmpty(WhatsNewsState s) {
    switch (s.scanMode) {
      case 'metrics':
        return s.metricScan.isEmpty;
      case 'setups':
        return s.setupScan.isEmpty;
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
      default:
        return _TrendTile(row: s.trendScan[i], onOpen: onOpenChart);
    }
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
