import 'package:flutter/cupertino.dart';

import '../data/app_state.dart';
import '../data/models.dart';
import 'theme.dart';

class BookPage extends StatelessWidget {
  const BookPage({super.key, required this.state, required this.onOpenChart});

  final WhatsNewsState state;
  final ValueChanged<String> onOpenChart;

  @override
  Widget build(BuildContext context) {
    final pnl = state.bookPnl;
    return CustomScrollView(
      slivers: [
        CupertinoSliverNavigationBar(
          backgroundColor: DeskColors.elevated,
          largeTitle: Text(pnl.deskName.isEmpty ? 'Whats-News' : pnl.deskName),
          trailing: CupertinoButton(
            padding: EdgeInsets.zero,
            onPressed: state.loadingBook ? null : state.loadBook,
            child: const Icon(CupertinoIcons.refresh),
          ),
        ),
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 8),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  'Paper book. Marks and VaR from stored Yahoo daily closes. Empty is zeros — not a demo P&L.',
                  style: TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35),
                ),
                const SizedBox(height: 10),
                Wrap(
                  spacing: 6,
                  children: [
                    _Chip(
                      label: 'P&L',
                      on: state.bookPane != 'positions',
                      onTap: () => state.setBookPane('pnl'),
                    ),
                    _Chip(
                      label: 'Positions',
                      on: state.bookPane == 'positions',
                      onTap: () => state.setBookPane('positions'),
                    ),
                  ],
                ),
                if (state.bookError != null) ...[
                  const SizedBox(height: 8),
                  Text(state.bookError!, style: const TextStyle(color: DeskColors.red, fontSize: 13)),
                ],
              ],
            ),
          ),
        ),
        if (state.bookPane == 'positions')
          ..._positionSlivers(state)
        else
          ..._pnlSlivers(state, pnl),
      ],
    );
  }

  List<Widget> _pnlSlivers(WhatsNewsState s, BookPnl pnl) {
    Color tone(double? v) {
      if (v == null) return DeskColors.muted;
      if (v > 0) return DeskColors.green;
      if (v < 0) return DeskColors.red;
      return DeskColors.text;
    }

    String pct(double? v) => v == null ? '—' : '${v >= 0 ? '+' : ''}${v.toStringAsFixed(2)}%';
    String usd(double? v) {
      if (v == null) return '—';
      final abs = v.abs().toStringAsFixed(2);
      return '${v < 0 ? '−' : ''}\$$abs';
    }

    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 8, 16, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('TODAY\'S P&L', style: TextStyle(color: DeskColors.dim, fontSize: 11, fontWeight: FontWeight.w700)),
              Text(
                pct(pnl.todayPnlPct),
                style: TextStyle(color: tone(pnl.todayPnlPct), fontSize: 48, fontWeight: FontWeight.w800, height: 1.05),
              ),
              Text(usd(pnl.todayPnl), style: TextStyle(color: tone(pnl.todayPnl), fontSize: 20, fontWeight: FontWeight.w600)),
              const SizedBox(height: 4),
              Text(
                pnl.nav == null ? 'NAV —' : 'NAV ${usd(pnl.nav)}',
                style: const TextStyle(color: DeskColors.muted, fontSize: 12),
              ),
              const SizedBox(height: 8),
              Text(
                pnl.curveLabel.isEmpty ? 'daily mark series from stored closes' : pnl.curveLabel,
                style: const TextStyle(color: DeskColors.dim, fontSize: 11),
              ),
              const SizedBox(height: 6),
              SizedBox(
                height: 88,
                width: double.infinity,
                child: CustomPaint(painter: _CurvePainter(pnl.curve.map((e) => e.$2).toList())),
              ),
              const SizedBox(height: 14),
              Wrap(
                spacing: 8,
                runSpacing: 8,
                children: [
                  _Metric('Gross', usd(pnl.gross)),
                  _Metric('Longs', usd(pnl.longMv)),
                  _Metric('Shorts', usd(pnl.shortMv)),
                  _Metric('Net', usd(pnl.net)),
                  _Metric('Beta vs SPY', pnl.betaSpy?.toStringAsFixed(2) ?? '—'),
                  _Metric('VaR 95% hist', pnl.hist95Pct == null ? '—' : '${pnl.hist95Pct!.toStringAsFixed(2)}%'),
                  _Metric('VaR 95% param', pnl.param95Pct == null ? '—' : '${pnl.param95Pct!.toStringAsFixed(2)}%'),
                  _Metric('ES 95%', pnl.es95Pct == null ? '—' : '${pnl.es95Pct!.toStringAsFixed(2)}%'),
                ],
              ),
              if (pnl.varNote.isNotEmpty) ...[
                const SizedBox(height: 8),
                Text(pnl.varNote, style: const TextStyle(color: DeskColors.dim, fontSize: 11)),
              ],
              const SizedBox(height: 8),
              Text(
                'Return dist n=${pnl.distN} · mean ${pnl.distMean?.toStringAsFixed(3) ?? '—'}% · σ ${pnl.distStdev?.toStringAsFixed(3) ?? '—'}%',
                style: const TextStyle(color: DeskColors.muted, fontSize: 11),
              ),
              const SizedBox(height: 12),
              Wrap(
                spacing: 8,
                runSpacing: 6,
                children: [
                  for (final t in pnl.tape)
                    GestureDetector(
                      onTap: () => onOpenChart(t.symbol),
                      child: Text(
                        '${t.symbol} ${t.ready ? pct(t.dayPct) : 'no bars'}',
                        style: TextStyle(color: tone(t.dayPct), fontSize: 13, fontWeight: FontWeight.w600),
                      ),
                    ),
                ],
              ),
              if (pnl.message.isNotEmpty) ...[
                const SizedBox(height: 12),
                Text(pnl.message, style: const TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35)),
              ],
            ],
          ),
        ),
      ),
    ];
  }

  List<Widget> _positionSlivers(WhatsNewsState s) {
    final rows = s.bookPnl.positions;
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(16, 0, 16, 8),
          child: Text(
            'Fidelity: Positions → download CSV (Symbol + Quantity; Cost Basis Average optional). No login, no orders.',
            style: const TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35),
          ),
        ),
      ),
      SliverToBoxAdapter(child: _AddLine(state: s)),
      if (rows.isEmpty)
        const SliverToBoxAdapter(
          child: Padding(
            padding: EdgeInsets.all(24),
            child: Text(
              'Empty paper book. Import a Fidelity CSV on the web Book tab, or add a line here.',
              style: TextStyle(color: DeskColors.muted, height: 1.4),
            ),
          ),
        )
      else
        SliverList.builder(
          itemCount: rows.length,
          itemBuilder: (context, i) {
            final r = rows[i];
            return Dismissible(
              key: ValueKey('book-${r.id ?? r.symbol}'),
              direction: DismissDirection.endToStart,
              onDismissed: (_) {
                if (r.id != null) s.removeBookLine(r.id!);
              },
              background: Container(color: DeskColors.red),
              child: GestureDetector(
                onTap: () => onOpenChart(r.symbol),
                child: Padding(
                  padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
                  child: Text(
                    [
                      r.symbol,
                      r.side,
                      r.qty?.toString() ?? '—',
                      r.ready ? (r.price?.toStringAsFixed(2) ?? '—') : 'no bars',
                      r.dayPnl == null ? '' : r.dayPnl!.toStringAsFixed(2),
                    ].where((e) => e.isNotEmpty).join(' · '),
                    style: TextStyle(
                      color: r.ready ? DeskColors.text : DeskColors.dim,
                      fontSize: 14,
                    ),
                  ),
                ),
              ),
            );
          },
        ),
    ];
  }
}

class _AddLine extends StatefulWidget {
  const _AddLine({required this.state});
  final WhatsNewsState state;

  @override
  State<_AddLine> createState() => _AddLineState();
}

class _AddLineState extends State<_AddLine> {
  final _sym = TextEditingController();
  final _qty = TextEditingController();
  String _side = 'long';

  @override
  void dispose() {
    _sym.dispose();
    _qty.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 12),
      child: Row(
        children: [
          Expanded(
            child: CupertinoTextField(
              controller: _sym,
              placeholder: 'Symbol',
              textCapitalization: TextCapitalization.characters,
              style: const TextStyle(color: DeskColors.text),
            ),
          ),
          const SizedBox(width: 6),
          SizedBox(
            width: 72,
            child: CupertinoTextField(
              controller: _qty,
              placeholder: 'Qty',
              keyboardType: const TextInputType.numberWithOptions(signed: true, decimal: true),
              style: const TextStyle(color: DeskColors.text),
            ),
          ),
          const SizedBox(width: 6),
          CupertinoButton(
            padding: const EdgeInsets.symmetric(horizontal: 8),
            onPressed: () => setState(() => _side = _side == 'long' ? 'short' : 'long'),
            child: Text(_side, style: const TextStyle(fontSize: 13)),
          ),
          CupertinoButton.filled(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            onPressed: () {
              final q = double.tryParse(_qty.text);
              if (_sym.text.trim().isEmpty || q == null || q == 0) return;
              widget.state.addBookLine(_sym.text.trim(), q, side: _side);
              _sym.clear();
              _qty.clear();
            },
            child: const Text('Add', style: TextStyle(fontSize: 13)),
          ),
        ],
      ),
    );
  }
}

class _Chip extends StatelessWidget {
  const _Chip({required this.label, required this.on, required this.onTap});
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

class _Metric extends StatelessWidget {
  const _Metric(this.k, this.v);
  final String k;
  final String v;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: 148,
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: DeskColors.card,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: DeskColors.border),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(k, style: const TextStyle(color: DeskColors.dim, fontSize: 11, fontWeight: FontWeight.w700)),
          const SizedBox(height: 4),
          Text(v, style: const TextStyle(color: DeskColors.text, fontSize: 16, fontWeight: FontWeight.w700)),
        ],
      ),
    );
  }
}

class _CurvePainter extends CustomPainter {
  _CurvePainter(this.values);
  final List<double> values;

  @override
  void paint(Canvas canvas, Size size) {
    final paint = Paint()
      ..color = DeskColors.accentBright
      ..strokeWidth = 2
      ..style = PaintingStyle.stroke;
    if (values.length < 2) {
      return;
    }
    final min = values.reduce((a, b) => a < b ? a : b);
    final max = values.reduce((a, b) => a > b ? a : b);
    final span = (max - min).abs() < 1e-9 ? 1.0 : max - min;
    final path = Path();
    for (var i = 0; i < values.length; i++) {
      final x = size.width * i / (values.length - 1);
      final y = size.height - ((values[i] - min) / span) * size.height;
      if (i == 0) {
        path.moveTo(x, y);
      } else {
        path.lineTo(x, y);
      }
    }
    canvas.drawPath(path, paint);
  }

  @override
  bool shouldRepaint(covariant _CurvePainter old) => old.values != values;
}
