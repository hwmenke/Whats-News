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
          backgroundColor: const Color(0xFF07090D),
          border: null,
          largeTitle: Text(
            (pnl.deskName.isEmpty ? 'Whats-News' : pnl.deskName).toUpperCase(),
            style: const TextStyle(letterSpacing: 3, fontSize: 18),
          ),
          trailing: CupertinoButton(
            padding: EdgeInsets.zero,
            onPressed: state.loadingBook ? null : state.loadBook,
            child: const Icon(CupertinoIcons.refresh),
          ),
        ),
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 8),
            child: Column(
              children: [
                Wrap(
                  spacing: 6,
                  alignment: WrapAlignment.center,
                  children: [
                    _Chip(
                      label: 'Upload',
                      on: state.bookPane == 'upload' || state.bookPane == 'positions',
                      onTap: () => state.setBookPane('upload'),
                    ),
                    _Chip(
                      label: 'P&L',
                      on: state.bookPane == 'pnl',
                      onTap: () => state.setBookPane('pnl'),
                    ),
                    _Chip(
                      label: 'Risk',
                      on: state.bookPane == 'risk',
                      onTap: () => state.setBookPane('risk'),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                const Text(
                  'Alpaca paper — not live P&L',
                  style: TextStyle(color: DeskColors.muted, fontSize: 12),
                ),
                if (state.alpacaMessage != null && state.alpacaMessage!.isNotEmpty)
                  Text(
                    state.alpacaMessage!,
                    style: const TextStyle(color: DeskColors.dim, fontSize: 11),
                    textAlign: TextAlign.center,
                  ),
                CupertinoButton(
                  padding: const EdgeInsets.symmetric(horizontal: 8),
                  onPressed: state.loadingBook ? null : state.syncAlpacaPaper,
                  child: const Text('Sync Alpaca paper', style: TextStyle(fontSize: 13)),
                ),
                if (state.bookError != null) ...[
                  const SizedBox(height: 8),
                  Text(state.bookError!, style: const TextStyle(color: DeskColors.red, fontSize: 13)),
                ],
              ],
            ),
          ),
        ),
        if (state.bookPane == 'upload' || state.bookPane == 'positions')
          ..._positionSlivers(state)
        else if (state.bookPane == 'risk')
          ..._riskSlivers(state, pnl)
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

    final mid = (pnl.tape.length / 2).ceil();
    final tapeA = mid == 0 ? const <BookPosition>[] : pnl.tape.take(mid).toList();
    final tapeB = mid == 0 ? const <BookPosition>[] : pnl.tape.skip(mid).toList();
    final netPct = pnl.gross == 0 ? '—' : '${(pnl.net / pnl.gross * 100).toStringAsFixed(0)}%';

    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          child: Column(
            children: [
              Text(
                pct(pnl.todayPnlPct),
                style: TextStyle(color: tone(pnl.todayPnlPct), fontSize: 64, fontWeight: FontWeight.w800, height: 0.95, letterSpacing: -1.5),
              ),
              const SizedBox(height: 4),
              const Text(
                'TODAY\'S P&L',
                style: TextStyle(color: DeskColors.text, fontSize: 13, letterSpacing: 2.4, fontWeight: FontWeight.w600),
              ),
              const SizedBox(height: 4),
              Text(usd(pnl.todayPnl), style: TextStyle(color: tone(pnl.todayPnl), fontSize: 26, fontWeight: FontWeight.w600)),
              const SizedBox(height: 10),
              Text(
                pnl.curveLabel.isEmpty ? 'daily mark series from stored closes — no intraday bars' : pnl.curveLabel,
                style: const TextStyle(color: DeskColors.dim, fontSize: 10),
                textAlign: TextAlign.center,
              ),
              const SizedBox(height: 6),
              SizedBox(
                height: 168,
                width: double.infinity,
                child: CustomPaint(painter: _CurvePainter(pnl.curve.map((e) => e.$2).toList())),
              ),
              const SizedBox(height: 8),
              _ExpRow('Equities', pnl.ready ? usd(pnl.gross) : '—'),
              _ExpRow('Longs', pnl.ready ? usd(pnl.longMv) : '—'),
              _ExpRow('Shorts', pnl.ready ? usd(pnl.shortMv) : '—'),
              _ExpRow('Net Exposure', pnl.ready ? netPct : '—'),
              const SizedBox(height: 14),
              if (tapeA.isNotEmpty)
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      for (final t in tapeA)
                        Padding(
                          padding: const EdgeInsets.only(right: 16),
                          child: GestureDetector(
                            onTap: () => onOpenChart(t.symbol),
                            child: Text.rich(TextSpan(children: [
                              TextSpan(text: '${t.symbol} ', style: const TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700)),
                              TextSpan(text: t.ready ? pct(t.dayPct) : '—', style: TextStyle(color: tone(t.dayPct), fontWeight: FontWeight.w600)),
                            ])),
                          ),
                        ),
                    ],
                  ),
                ),
              if (tapeB.isNotEmpty) ...[
                const SizedBox(height: 8),
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: [
                      for (final t in tapeB)
                        Padding(
                          padding: const EdgeInsets.only(right: 16),
                          child: GestureDetector(
                            onTap: () => onOpenChart(t.symbol),
                            child: Text.rich(TextSpan(children: [
                              TextSpan(text: '${t.symbol} ', style: const TextStyle(color: DeskColors.text, fontWeight: FontWeight.w700)),
                              TextSpan(text: t.ready ? pct(t.dayPct) : '—', style: TextStyle(color: tone(t.dayPct), fontWeight: FontWeight.w600)),
                            ])),
                          ),
                        ),
                    ],
                  ),
                ),
              ],
              if (pnl.message.isNotEmpty) ...[
                const SizedBox(height: 10),
                Text(pnl.message, style: const TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35)),
              ],
            ],
          ),
        ),
      ),
    ];
  }

  List<Widget> _riskSlivers(WhatsNewsState s, BookPnl pnl) {
    String usd(double? v) {
      if (v == null) return '—';
      final abs = v.abs().toStringAsFixed(2);
      return '${v < 0 ? '−' : ''}\$$abs';
    }

    final rows = pnl.positions;
    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                'Portfolio risk',
                style: TextStyle(fontWeight: FontWeight.w700, letterSpacing: 0.4),
              ),
              const SizedBox(height: 8),
              Wrap(
                spacing: 6,
                runSpacing: 6,
                children: [
                  if (pnl.topWeightPct != null)
                    _RiskChip('Top ${pnl.topSymbol.isEmpty ? '' : '${pnl.topSymbol} '}${pnl.topWeightPct!.toStringAsFixed(0)}%'),
                  if (pnl.hhi != null) _RiskChip('HHI ${pnl.hhi!.toStringAsFixed(0)}'),
                  if (pnl.maxDdPct != null) _RiskChip('Max DD ${pnl.maxDdPct!.toStringAsFixed(1)}%'),
                  if (pnl.betaSpy != null) _RiskChip('β ${pnl.betaSpy!.toStringAsFixed(2)}'),
                  for (final a in pnl.alerts) _RiskChip(a, alert: true),
                ],
              ),
              const SizedBox(height: 10),
              _ExpRow('Net', usd(pnl.net)),
              _ExpRow('Beta', pnl.betaSpy?.toStringAsFixed(2) ?? '—'),
              _ExpRow('Top weight', pnl.topWeightPct == null ? '—' : '${pnl.topWeightPct!.toStringAsFixed(1)}%'),
              _ExpRow('HHI', pnl.hhi?.toStringAsFixed(0) ?? '—'),
              _ExpRow('Max DD', pnl.maxDdPct == null ? '—' : '${pnl.maxDdPct!.toStringAsFixed(1)}%'),
              const SizedBox(height: 10),
              Text(
                'VaR hist 95% ${pnl.hist95Pct?.toStringAsFixed(2) ?? '—'}% · param ${pnl.param95Pct?.toStringAsFixed(2) ?? '—'}% · ES ${pnl.es95Pct?.toStringAsFixed(2) ?? '—'}%',
                style: const TextStyle(color: DeskColors.dim, fontSize: 11, height: 1.4),
              ),
              const SizedBox(height: 16),
              const Text(
                'Per-name risk',
                style: TextStyle(fontWeight: FontWeight.w700, letterSpacing: 0.4),
              ),
              const SizedBox(height: 4),
              const Text(
                'Weight · stand-alone 30d vol · risk contribution. Blank if bars are missing.',
                style: TextStyle(color: DeskColors.muted, fontSize: 11),
              ),
            ],
          ),
        ),
      ),
      if (rows.isEmpty)
        const SliverToBoxAdapter(
          child: Padding(
            padding: EdgeInsets.all(24),
            child: Text(
              'No marked names. Import a book and Fetch Yahoo so weight / vol / VaR can compute.',
              style: TextStyle(color: DeskColors.muted, height: 1.4),
            ),
          ),
        )
      else
        SliverList.builder(
          itemCount: rows.length,
          itemBuilder: (context, i) {
            final r = rows[i];
            return GestureDetector(
              onTap: () => onOpenChart(r.symbol),
              child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 6, 20, 6),
                child: Text(
                  [
                    r.symbol,
                    r.weightPct == null ? 'wt —' : 'wt ${r.weightPct!.toStringAsFixed(1)}%',
                    r.vol30 == null ? 'vol —' : 'vol ${r.vol30!.toStringAsFixed(1)}%',
                    r.riskContribPct == null ? 'rc —' : 'rc ${r.riskContribPct!.toStringAsFixed(1)}%',
                    if (r.concentrated) 'CONCENTRATED',
                  ].join(' · '),
                  style: TextStyle(
                    color: r.ready ? DeskColors.text : DeskColors.dim,
                    fontSize: 13,
                  ),
                ),
              ),
            );
          },
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
      SliverToBoxAdapter(child: _CsvPaste(state: s)),
      SliverToBoxAdapter(child: _AddLine(state: s)),
      if (rows.isEmpty)
        const SliverToBoxAdapter(
          child: Padding(
            padding: EdgeInsets.all(24),
            child: Text(
              'Empty paper book. Paste a Fidelity CSV or add a line. Marks stay blank until Yahoo bars are stored.',
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
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        [
                          r.symbol,
                          r.side,
                          r.source,
                          r.qty?.toString() ?? '—',
                          r.ready ? (r.price?.toStringAsFixed(2) ?? '—') : 'no bars',
                          r.dayPnl == null ? '' : r.dayPnl!.toStringAsFixed(2),
                        ].where((e) => e.isNotEmpty).join(' · '),
                        style: TextStyle(
                          color: r.ready ? DeskColors.text : DeskColors.dim,
                          fontSize: 14,
                        ),
                      ),
                      if (r.ready)
                        Text(
                          [
                            if (r.dayPct != null) 'day ${r.dayPct!.toStringAsFixed(2)}%',
                            if (r.vsSma50 != null) 'vs50 ${r.vsSma50!.toStringAsFixed(1)}%',
                            if (r.rsi14 != null) 'RSI ${r.rsi14!.toStringAsFixed(1)}',
                            if (r.fractalRead != null && r.fractalRead!.isNotEmpty) r.fractalRead!,
                            if (r.hmmLabel != null && r.hmmLabel!.isNotEmpty) 'HMM ${r.hmmLabel!}',
                          ].join(' · '),
                          style: const TextStyle(color: DeskColors.muted, fontSize: 11),
                        ),
                    ],
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

class _RiskChip extends StatelessWidget {
  const _RiskChip(this.label, {this.alert = false});
  final String label;
  final bool alert;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: alert ? const Color(0x33EF4444) : DeskColors.card,
        borderRadius: BorderRadius.circular(6),
        border: Border.all(color: alert ? DeskColors.red : DeskColors.border),
      ),
      child: Text(
        label,
        style: TextStyle(
          color: alert ? DeskColors.red : DeskColors.muted,
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
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

class _CsvPaste extends StatefulWidget {
  const _CsvPaste({required this.state});
  final WhatsNewsState state;

  @override
  State<_CsvPaste> createState() => _CsvPasteState();
}

class _CsvPasteState extends State<_CsvPaste> {
  final _csv = TextEditingController();
  String? _msg;
  bool _replace = false;

  @override
  void dispose() {
    _csv.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 0, 16, 10),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          CupertinoTextField(
            controller: _csv,
            placeholder: 'Paste Fidelity Positions CSV…',
            maxLines: 4,
            style: const TextStyle(color: DeskColors.text, fontSize: 12),
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              CupertinoButton(
                padding: EdgeInsets.zero,
                onPressed: () => setState(() => _replace = !_replace),
                child: Text(_replace ? 'Replace on' : 'Replace off', style: const TextStyle(fontSize: 12)),
              ),
              const Spacer(),
              CupertinoButton.filled(
                padding: const EdgeInsets.symmetric(horizontal: 12),
                onPressed: () async {
                  final text = _csv.text.trim();
                  if (text.isEmpty) return;
                  final msg = await widget.state.importBookCsv(text, replace: _replace);
                  setState(() => _msg = msg);
                },
                child: const Text('Import CSV', style: TextStyle(fontSize: 13)),
              ),
            ],
          ),
          if (_msg != null) Text(_msg!, style: const TextStyle(color: DeskColors.muted, fontSize: 12)),
        ],
      ),
    );
  }
}

class _ExpRow extends StatelessWidget {
  const _ExpRow(this.k, this.v);
  final String k;
  final String v;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(vertical: 11),
      decoration: const BoxDecoration(
        border: Border(bottom: BorderSide(color: Color(0xFF2A3140))),
      ),
      child: Row(
        children: [
          Text(k, style: const TextStyle(color: DeskColors.text, fontSize: 16)),
          const Spacer(),
          Text(v, style: const TextStyle(color: DeskColors.text, fontSize: 16, fontWeight: FontWeight.w500)),
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
    final grid = Paint()
      ..color = const Color(0xFF2A3140)
      ..strokeWidth = 1;
    for (var i = 1; i < 5; i++) {
      final y = size.height * i / 5;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
      final x = size.width * i / 5;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), grid);
    }
    if (values.length < 2) {
      return;
    }
    final min = values.reduce((a, b) => a < b ? a : b);
    final max = values.reduce((a, b) => a > b ? a : b);
    final span = (max - min).abs() < 1e-9 ? 1.0 : max - min;
    final open = values.first;
    Offset pt(int i) => Offset(
          size.width * i / (values.length - 1),
          size.height - ((values[i] - min) / span) * size.height,
        );
    for (var i = 1; i < values.length; i++) {
      final paint = Paint()
        ..color = values[i] >= open ? DeskColors.green : DeskColors.red
        ..strokeWidth = 2.2
        ..style = PaintingStyle.stroke;
      canvas.drawLine(pt(i - 1), pt(i), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _CurvePainter old) => old.values != values;
}
