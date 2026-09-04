import 'package:flutter/cupertino.dart';

import '../data/app_state.dart';
import 'candles.dart';
import 'theme.dart';

class ChartPage extends StatelessWidget {
  const ChartPage({super.key, required this.state});

  final WhatsNewsState state;

  @override
  Widget build(BuildContext context) {
    final bar = state.displayBar;
    final chg = state.sessionChangePct;
    final up = (chg ?? 0) >= 0;
    final chgColor = chg == null
        ? DeskColors.muted
        : (up ? DeskColors.green : DeskColors.red);
    final title = state.selectedSymbol ?? 'Chart';
    final hasBars = state.bars.isNotEmpty;

    return Column(
      crossAxisAlignment: CrossAxisAlignment.stretch,
      children: [
        CupertinoNavigationBar(
          backgroundColor: DeskColors.elevated,
          middle: Text(title),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 10, 16, 6),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              if (hasBars && bar != null)
                Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      bar.close.toStringAsFixed(2),
                      style: const TextStyle(
                        color: DeskColors.text,
                        fontSize: 28,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const SizedBox(width: 10),
                    if (chg != null)
                      Text(
                        '${up ? '+' : ''}${chg.toStringAsFixed(2)}%',
                        style: TextStyle(
                          color: chgColor,
                          fontSize: 16,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    const Spacer(),
                    _FreqSeg(state: state),
                  ],
                )
              else
                Row(
                  children: [
                    Expanded(
                      child: Text(
                        state.loadingChart
                            ? 'Loading stored bars…'
                            : 'Yahoo bars from finance.db — no invented prices',
                        style: const TextStyle(
                          color: DeskColors.muted,
                          fontSize: 13,
                        ),
                      ),
                    ),
                    _FreqSeg(state: state),
                  ],
                ),
              if (hasBars && bar != null)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    '${bar.date}  O ${bar.open.toStringAsFixed(2)}  '
                    'H ${bar.high.toStringAsFixed(2)}  '
                    'L ${bar.low.toStringAsFixed(2)}  '
                    'C ${bar.close.toStringAsFixed(2)}',
                    style: const TextStyle(
                      color: DeskColors.muted,
                      fontSize: 12,
                      fontFamily: 'Courier',
                    ),
                  ),
                ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  _OverlayPill(
                    label: 'KAMA 10',
                    color: DeskColors.kama10,
                    on: state.showKama10,
                    onTap: () => state.toggleOverlay('kama10'),
                  ),
                  _OverlayPill(
                    label: 'KAMA 20',
                    color: DeskColors.kama20,
                    on: state.showKama20,
                    onTap: () => state.toggleOverlay('kama20'),
                  ),
                  _OverlayPill(
                    label: 'KAMA 50',
                    color: DeskColors.kama50,
                    on: state.showKama50,
                    onTap: () => state.toggleOverlay('kama50'),
                  ),
                  _OverlayPill(
                    label: 'BB 20',
                    color: DeskColors.muted,
                    on: state.showBollinger,
                    onTap: () => state.toggleOverlay('bb'),
                  ),
                ],
              ),
            ],
          ),
        ),
        Expanded(
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
            child: DecoratedBox(
              decoration: BoxDecoration(
                color: DeskColors.card,
                borderRadius: BorderRadius.circular(12),
                border: Border.all(color: DeskColors.border),
              ),
              child: ClipRRect(
                borderRadius: BorderRadius.circular(12),
                child: state.loadingChart
                    ? const Center(child: CupertinoActivityIndicator())
                    : CandleChart(
                        bars: state.bars,
                        indicators: state.indicators,
                        showKama10: state.showKama10,
                        showKama20: state.showKama20,
                        showKama50: state.showKama50,
                        showBollinger: state.showBollinger,
                        onScrub: state.setScrubBar,
                      ),
              ),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (state.chartError != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(
                    state.chartError!,
                    style: const TextStyle(color: DeskColors.red, fontSize: 13),
                  ),
                ),
              if (state.throttleMessage != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(
                    state.throttleMessage!,
                    style: const TextStyle(color: Color(0xFFEAB308), fontSize: 13),
                  ),
                ),
              Row(
                children: [
                  Expanded(
                    child: CupertinoButton.filled(
                      onPressed: state.fetching || state.selectedSymbol == null
                          ? null
                          : () => state.fetchFromYahoo(),
                      child: state.fetching
                          ? const CupertinoActivityIndicator()
                          : const Text('Fetch from Yahoo'),
                    ),
                  ),
                ],
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _OverlayPill extends StatelessWidget {
  const _OverlayPill({
    required this.label,
    required this.color,
    required this.on,
    required this.onTap,
  });

  final String label;
  final Color color;
  final bool on;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
        decoration: BoxDecoration(
          color: on ? color.withValues(alpha: 0.22) : DeskColors.card,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: on ? color : DeskColors.border),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: on ? color : DeskColors.muted,
            fontSize: 11,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

class _FreqSeg extends StatelessWidget {
  const _FreqSeg({required this.state});

  final WhatsNewsState state;

  @override
  Widget build(BuildContext context) {
    return CupertinoSlidingSegmentedControl<String>(
      groupValue: state.freq,
      children: const {
        'daily': Padding(
          padding: EdgeInsets.symmetric(horizontal: 6),
          child: Text('D', style: TextStyle(fontSize: 13)),
        ),
        'weekly': Padding(
          padding: EdgeInsets.symmetric(horizontal: 6),
          child: Text('W', style: TextStyle(fontSize: 13)),
        ),
        'monthly': Padding(
          padding: EdgeInsets.symmetric(horizontal: 6),
          child: Text('M', style: TextStyle(fontSize: 13)),
        ),
      },
      onValueChanged: (v) {
        if (v != null) state.setFreq(v);
      },
    );
  }
}
