import 'package:flutter/cupertino.dart';

import '../data/app_state.dart';
import '../data/models.dart';
import 'theme.dart';

class WatchlistPage extends StatefulWidget {
  const WatchlistPage({
    super.key,
    required this.state,
    required this.onOpenChart,
    required this.onOpenSettings,
  });

  final WhatsNewsState state;
  final ValueChanged<String> onOpenChart;
  final VoidCallback onOpenSettings;

  @override
  State<WatchlistPage> createState() => _WatchlistPageState();
}

class _WatchlistPageState extends State<WatchlistPage> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    return CustomScrollView(
      slivers: [
        CupertinoSliverNavigationBar(
          backgroundColor: DeskColors.elevated,
          largeTitle: const Text('Watchlist'),
          trailing: CupertinoButton(
            padding: EdgeInsets.zero,
            onPressed: widget.onOpenSettings,
            child: const Icon(CupertinoIcons.gear),
          ),
        ),
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.stretch,
              children: [
                const Text(
                  'Paper / local only — no live trading.',
                  style: TextStyle(color: DeskColors.muted, fontSize: 12),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: CupertinoTextField(
                        controller: _controller,
                        placeholder: 'Add ticker',
                        textCapitalization: TextCapitalization.characters,
                        autocorrect: false,
                        style: const TextStyle(color: DeskColors.text),
                        placeholderStyle:
                            const TextStyle(color: DeskColors.dim),
                        decoration: BoxDecoration(
                          color: DeskColors.card,
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(color: DeskColors.border),
                        ),
                        padding: const EdgeInsets.symmetric(
                          horizontal: 12,
                          vertical: 10,
                        ),
                        onSubmitted: (_) => _add(),
                      ),
                    ),
                    const SizedBox(width: 8),
                    CupertinoButton.filled(
                      padding: const EdgeInsets.symmetric(horizontal: 14),
                      onPressed: _add,
                      child: const Text('+'),
                    ),
                  ],
                ),
                if (state.throttleMessage != null) ...[
                  const SizedBox(height: 8),
                  _Banner(
                    text: state.throttleMessage!,
                    color: const Color(0xFFEAB308),
                  ),
                ],
                if (state.error != null) ...[
                  const SizedBox(height: 8),
                  _Banner(text: state.error!, color: DeskColors.red),
                ],
              ],
            ),
          ),
        ),
        if (state.loadingWatchlist && state.symbols.isEmpty)
          const SliverFillRemaining(
            child: Center(child: CupertinoActivityIndicator()),
          )
        else if (state.symbols.isEmpty)
          SliverFillRemaining(
            hasScrollBody: false,
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Text(
                'Empty desk.\n\nType AAPL, tap +, then Fetch from Yahoo on the Chart tab.\nHeadlines land on News — same Yahoo stories as the Dash app.',
                style: const TextStyle(color: DeskColors.muted, height: 1.4),
              ),
            ),
          )
        else
          SliverList.builder(
            itemCount: state.symbols.length,
            itemBuilder: (context, i) {
              final s = state.symbols[i];
              final selected = s.symbol == state.selectedSymbol;
              return Dismissible(
                key: ValueKey(s.symbol),
                direction: DismissDirection.endToStart,
                background: Container(
                  color: DeskColors.red,
                  alignment: Alignment.centerRight,
                  padding: const EdgeInsets.only(right: 20),
                  child: const Icon(CupertinoIcons.delete, color: DeskColors.text),
                ),
                onDismissed: (_) => state.removeSymbol(s.symbol),
                child: _SymbolTile(
                  symbol: s,
                  selected: selected,
                  onTap: () => widget.onOpenChart(s.symbol),
                ),
              );
            },
          ),
      ],
    );
  }

  Future<void> _add() async {
    final text = _controller.text;
    _controller.clear();
    await widget.state.addSymbol(text);
  }
}

class _SymbolTile extends StatelessWidget {
  const _SymbolTile({
    required this.symbol,
    required this.selected,
    required this.onTap,
  });

  final WatchSymbol symbol;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        color: selected ? DeskColors.hover : DeskColors.bg,
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        child: Row(
          children: [
            Container(
              width: 4,
              height: 28,
              decoration: BoxDecoration(
                color: selected ? DeskColors.accent : DeskColors.border,
                borderRadius: BorderRadius.circular(2),
              ),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    symbol.symbol,
                    style: const TextStyle(
                      color: DeskColors.text,
                      fontWeight: FontWeight.w600,
                      fontSize: 17,
                    ),
                  ),
                  if (symbol.name.isNotEmpty)
                    Text(
                      symbol.name,
                      style: const TextStyle(
                        color: DeskColors.muted,
                        fontSize: 12,
                      ),
                    ),
                ],
              ),
            ),
            const Icon(CupertinoIcons.chart_bar, color: DeskColors.muted, size: 18),
          ],
        ),
      ),
    );
  }
}

class _Banner extends StatelessWidget {
  const _Banner({required this.text, required this.color});

  final String text;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.15),
        borderRadius: BorderRadius.circular(8),
        border: Border.all(color: color.withValues(alpha: 0.4)),
      ),
      child: Text(text, style: TextStyle(color: color, fontSize: 13)),
    );
  }
}
