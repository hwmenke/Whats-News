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
                const SizedBox(height: 10),
                _MacroBoard(
                  state: state,
                  onOpen: widget.onOpenChart,
                ),
                const SizedBox(height: 10),
                _FamilyChips(state: state),
              ],
            ),
          ),
        ),
        if (state.loadingWatchlist && state.symbols.isEmpty)
          const SliverFillRemaining(
            child: Center(child: CupertinoActivityIndicator()),
          )
        else if (state.visibleSymbols.isEmpty)
          SliverFillRemaining(
            hasScrollBody: false,
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Text(
                state.symbols.isEmpty
                    ? 'Empty desk.\n\nSeed a Macro sleeve or Core 50, or type AAPL and tap +. Cards light up after Fetch from Yahoo — no invented prices.'
                    : 'No names in this Country / Sector / Theme filter.',
                style: const TextStyle(color: DeskColors.muted, height: 1.4),
              ),
            ),
          )
        else
          SliverList.builder(
            itemCount: state.visibleSymbols.length,
            itemBuilder: (context, i) {
              final s = state.visibleSymbols[i];
              final selected = s.symbol == state.selectedSymbol;
              final tape = state.snapshot.named(s.symbol);
              final setup = state.setupFor(s.symbol);
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
                  tape: tape,
                  setup: setup,
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

class _FamilyChips extends StatelessWidget {
  const _FamilyChips({required this.state});
  final WhatsNewsState state;

  @override
  Widget build(BuildContext context) {
    Widget chip(String id, String label) {
      final on = state.familyFilter == id;
      return GestureDetector(
        onTap: () => state.setFamilyFilter(id),
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
              fontSize: 11,
              fontWeight: FontWeight.w600,
            ),
          ),
        ),
      );
    }

    return Wrap(
      spacing: 6,
      runSpacing: 6,
      children: [
        chip('', 'All'),
        chip('country', 'Country'),
        chip('sector', 'Sector'),
        chip('theme', 'Theme'),
      ],
    );
  }
}

class _MacroBoard extends StatelessWidget {
  const _MacroBoard({required this.state, required this.onOpen});
  final WhatsNewsState state;
  final ValueChanged<String> onOpen;

  @override
  Widget build(BuildContext context) {
    final board = state.macroBoard;
    return Container(
      decoration: BoxDecoration(
        color: DeskColors.card,
        borderRadius: BorderRadius.circular(12),
        border: Border.all(color: DeskColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          GestureDetector(
            onTap: state.toggleMacro,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 12, 8),
              child: Row(
                children: [
                  Text(
                    state.macroOpen ? '▼ Macro' : '▶ Macro',
                    style: const TextStyle(
                      color: DeskColors.text,
                      fontWeight: FontWeight.w700,
                      fontSize: 14,
                    ),
                  ),
                  const Spacer(),
                  if (state.loadingMacro)
                    const CupertinoActivityIndicator(radius: 8),
                ],
              ),
            ),
          ),
          if (state.macroOpen) ...[
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
              child: _RegimeLine(state: state),
            ),
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
              child: Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  _SeedChip(
                    label: 'Core 50',
                    busy: state.seedingSleeve,
                    filled: true,
                    onTap: state.seedCore50,
                  ),
                  for (final sleeve in board.sleeves)
                    _SeedChip(
                      label: '${sleeve.label} ${sleeve.readyCount}/${sleeve.tickers.length}',
                      busy: state.seedingSleeve,
                      onTap: () => state.seedSleeve(sleeve.id),
                    ),
                ],
              ),
            ),
            if (board.sleeves.isEmpty && !state.loadingMacro)
              const Padding(
                padding: EdgeInsets.fromLTRB(12, 0, 12, 12),
                child: Text(
                  'Macro board empty until the Python API is up. Start ./start.sh',
                  style: TextStyle(color: DeskColors.muted, fontSize: 12),
                ),
              )
            else
              ...[
                for (final sleeve in board.sleeves.take(6))
                  _SleeveCard(sleeve: sleeve, onOpen: onOpen),
                if (board.sleeves.length > 6)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
                    child: Text(
                      '+ ${board.sleeves.length - 6} more sleeves in Settings / Scans · Edges',
                      style: const TextStyle(color: DeskColors.dim, fontSize: 11),
                    ),
                  ),
              ],
          ],
        ],
      ),
    );
  }
}

class _RegimeLine extends StatelessWidget {
  const _RegimeLine({required this.state});
  final WhatsNewsState state;

  @override
  Widget build(BuildContext context) {
    final r = state.macroBoard.regime;
    if (!r.ready) {
      return GestureDetector(
        onTap: state.fetchVix,
        child: Text(
          r.note.isEmpty
              ? 'No stored VIX — tap to fetch ^VIX (not invented).'
              : r.note,
          style: const TextStyle(color: DeskColors.muted, fontSize: 12),
        ),
      );
    }
    return Text(
      '${r.label} · VIX ${r.vix?.toStringAsFixed(1) ?? '—'}'
      '${r.percentile1y != null ? ' · ${r.percentile1y}th %ile 1y' : ''}',
      style: const TextStyle(
        color: DeskColors.accentBright,
        fontSize: 12,
        fontWeight: FontWeight.w700,
      ),
    );
  }
}

class _SeedChip extends StatelessWidget {
  const _SeedChip({
    required this.label,
    required this.onTap,
    this.busy = false,
    this.filled = false,
  });

  final String label;
  final VoidCallback onTap;
  final bool busy;
  final bool filled;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: busy ? null : onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
        decoration: BoxDecoration(
          color: filled
              ? DeskColors.accent.withValues(alpha: 0.25)
              : DeskColors.elevated,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: filled ? DeskColors.accent : DeskColors.border),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: filled ? DeskColors.accentBright : DeskColors.muted,
            fontSize: 11,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

class _SleeveCard extends StatelessWidget {
  const _SleeveCard({required this.sleeve, required this.onOpen});
  final MacroSleeveBlock sleeve;
  final ValueChanged<String> onOpen;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(12, 0, 12, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            '${sleeve.label}  ${sleeve.readyCount}/${sleeve.tickers.length} lit',
            style: const TextStyle(
              color: DeskColors.text,
              fontSize: 12,
              fontWeight: FontWeight.w700,
            ),
          ),
          if (sleeve.skipped.isNotEmpty)
            Text(sleeve.skipped, style: const TextStyle(color: Color(0xFFEAB308), fontSize: 10)),
          const SizedBox(height: 4),
          for (final row in sleeve.rows.take(8))
            GestureDetector(
              onTap: row.ready ? () => onOpen(row.symbol) : null,
              child: Padding(
                padding: const EdgeInsets.symmetric(vertical: 2),
                child: Row(
                  children: [
                    SizedBox(
                      width: 56,
                      child: Text(
                        row.symbol,
                        style: TextStyle(
                          color: row.ready ? DeskColors.text : DeskColors.dim,
                          fontSize: 12,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                    ),
                    Expanded(
                      child: Text(
                        row.ready
                            ? '${row.px?.toStringAsFixed(2) ?? '—'}   ${_pct(row.dayPct)}   z ${_num(row.z30)}'
                            : 'no bars',
                        style: TextStyle(
                          color: row.extreme
                              ? const Color(0xFFF59E0B)
                              : (row.dayPct ?? 0) >= 0
                                  ? DeskColors.green
                                  : DeskColors.red,
                          fontSize: 11,
                          fontFamily: 'Courier',
                        ),
                      ),
                    ),
                    if (row.extreme)
                      const Text('|z|≥2', style: TextStyle(color: Color(0xFFF59E0B), fontSize: 10)),
                  ],
                ),
              ),
            ),
        ],
      ),
    );
  }

  String _pct(double? v) {
    if (v == null) return '—';
    return '${v >= 0 ? '+' : ''}${v.toStringAsFixed(1)}%';
  }

  String _num(double? v) => v == null ? '—' : v.toStringAsFixed(2);
}

class _SymbolTile extends StatelessWidget {
  const _SymbolTile({
    required this.symbol,
    required this.selected,
    required this.onTap,
    this.tape,
    this.setup,
  });

  final WatchSymbol symbol;
  final bool selected;
  final VoidCallback onTap;
  final TapeRow? tape;
  final SetupScanRow? setup;

  @override
  Widget build(BuildContext context) {
    final tags = <String>[
      if (tape?.isEp == true || setup?.isEp == true) 'EP',
      if (tape?.isVolSurge == true || setup?.isVolSurge == true) 'VOL',
      if (tape?.isNearHigh == true || setup?.setups.contains('NEAR_HIGH') == true) 'HI',
      if (setup?.isHighAdr == true) 'ADR≥4',
    ];
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
                  Row(
                    children: [
                      Text(
                        symbol.symbol,
                        style: const TextStyle(
                          color: DeskColors.text,
                          fontWeight: FontWeight.w600,
                          fontSize: 17,
                        ),
                      ),
                      if (tape?.changePct != null) ...[
                        const SizedBox(width: 8),
                        Text(
                          '${tape!.changePct! >= 0 ? '+' : ''}${tape!.changePct!.toStringAsFixed(1)}%',
                          style: TextStyle(
                            color: tape!.changePct! >= 0 ? DeskColors.green : DeskColors.red,
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ],
                    ],
                  ),
                  Text(
                    [
                      if (symbol.groupTag.isNotEmpty) symbol.groupTag,
                      if (tape?.regime != null) tape!.regime!,
                      ...tags,
                    ].join(' · '),
                    style: const TextStyle(color: DeskColors.muted, fontSize: 12),
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
