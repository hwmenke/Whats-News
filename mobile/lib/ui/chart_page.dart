import 'package:flutter/cupertino.dart';

import '../data/app_state.dart';
import 'candles.dart';
import 'theme.dart';

class ChartPage extends StatelessWidget {
  const ChartPage({super.key, required this.state});

  final WhatsNewsState state;

  @override
  Widget build(BuildContext context) {
    final last = state.lastBar;
    final chg = state.sessionChangePct;
    final up = (chg ?? 0) >= 0;
    final chgColor = chg == null
        ? DeskColors.muted
        : (up ? DeskColors.green : DeskColors.red);
    final title = state.selectedSymbol ?? 'Chart';

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
              if (last != null)
                Row(
                  crossAxisAlignment: CrossAxisAlignment.end,
                  children: [
                    Text(
                      last.close.toStringAsFixed(2),
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
                    const Expanded(
                      child: Text(
                        'Yahoo daily / weekly bars from finance.db',
                        style: TextStyle(color: DeskColors.muted, fontSize: 13),
                      ),
                    ),
                    _FreqSeg(state: state),
                  ],
                ),
              if (last != null)
                Padding(
                  padding: const EdgeInsets.only(top: 4),
                  child: Text(
                    'O ${last.open.toStringAsFixed(2)}  H ${last.high.toStringAsFixed(2)}  '
                    'L ${last.low.toStringAsFixed(2)}  C ${last.close.toStringAsFixed(2)}',
                    style: const TextStyle(
                      color: DeskColors.muted,
                      fontSize: 12,
                      fontFamily: 'Courier',
                    ),
                  ),
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
                    : CandleChart(bars: state.bars),
              ),
            ),
          ),
        ),
        Padding(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              if (state.error != null)
                Padding(
                  padding: const EdgeInsets.only(bottom: 8),
                  child: Text(
                    state.error!,
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
              CupertinoButton.filled(
                onPressed: state.fetching || state.selectedSymbol == null
                    ? null
                    : () => state.fetchFromYahoo(),
                child: state.fetching
                    ? const CupertinoActivityIndicator()
                    : const Text('Fetch from Yahoo'),
              ),
            ],
          ),
        ),
      ],
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
          padding: EdgeInsets.symmetric(horizontal: 8),
          child: Text('D', style: TextStyle(fontSize: 13)),
        ),
        'weekly': Padding(
          padding: EdgeInsets.symmetric(horizontal: 8),
          child: Text('W', style: TextStyle(fontSize: 13)),
        ),
      },
      onValueChanged: (v) {
        if (v != null) state.setFreq(v);
      },
    );
  }
}
