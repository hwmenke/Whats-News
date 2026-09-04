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
        SliverToBoxAdapter(
          child: SizedBox(
            height: DeskSpace.chrome,
            child: Padding(
              padding: DeskSpace.pageX,
              child: Row(
                children: [
                  _Chip(
                    label: 'Upload',
                    on: state.bookPane == 'upload' || state.bookPane == 'positions',
                    onTap: () => state.setBookPane('upload'),
                  ),
                  const SizedBox(width: 4),
                  _Chip(
                    label: 'P&L',
                    on: state.bookPane == 'pnl',
                    onTap: () => state.setBookPane('pnl'),
                  ),
                  const SizedBox(width: 4),
                  _Chip(
                    label: 'Risk',
                    on: state.bookPane == 'risk',
                    onTap: () => state.setBookPane('risk'),
                  ),
                  const Spacer(),
                  CupertinoButton(
                    padding: EdgeInsets.zero,
                    minSize: DeskSpace.chrome,
                    onPressed: state.loadingBook ? null : state.loadBook,
                    child: const Icon(CupertinoIcons.refresh, size: 16),
                  ),
                ],
              ),
            ),
          ),
        ),
        if (state.bookError != null && state.bookPane != 'risk')
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.fromLTRB(DeskSpace.inset, DeskSpace.headerContent, DeskSpace.inset, 0),
              child: Text(state.bookError!, style: const TextStyle(color: DeskColors.red, fontSize: 12)),
            ),
          ),
        if (state.bookPane == 'upload' || state.bookPane == 'positions')
          ..._positionSlivers(state)
        else if (state.bookPane == 'risk')
          ..._riskSlivers(state, pnl)
        else
          ..._pnlSlivers(state, pnl),
        SliverToBoxAdapter(child: SizedBox(height: DeskSpace.bottomInset(context))),
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

    final netPct = pnl.gross == 0 ? '—' : '${(pnl.net / pnl.gross * 100).toStringAsFixed(0)}%';
    final curveLabel = pnl.curveLabel.isEmpty
        ? 'daily mark series from stored closes — no intraday bars'
        : pnl.curveLabel;
    final exp = <(String, String)>[
      ('NAV', pnl.nav == null ? '—' : usd(pnl.nav)),
      ('Equities', pnl.ready ? usd(pnl.gross) : '—'),
      ('Longs', pnl.ready ? usd(pnl.longMv) : '—'),
      ('Shorts', pnl.ready ? usd(pnl.shortMv) : '—'),
      ('Net', pnl.ready ? netPct : '—'),
    ];

    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(DeskSpace.inset, DeskSpace.headerContent, DeskSpace.inset, 0),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              SizedBox(
                height: DeskSpace.row,
                child: Row(
                  children: [
                    const Text(
                      'TODAY\'S P&L',
                      style: TextStyle(
                        color: DeskColors.muted,
                        fontSize: 11,
                        letterSpacing: 0.4,
                        fontWeight: FontWeight.w700,
                      ),
                    ),
                    const Spacer(),
                    Text(
                      pct(pnl.todayPnlPct),
                      style: TextStyle(
                        color: tone(pnl.todayPnlPct),
                        fontSize: 16,
                        fontWeight: FontWeight.w700,
                        fontFamily: 'Courier',
                      ),
                    ),
                    const SizedBox(width: DeskSpace.cellX),
                    Text(
                      usd(pnl.todayPnl),
                      style: TextStyle(
                        color: tone(pnl.todayPnl),
                        fontSize: 13,
                        fontFamily: 'Courier',
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: DeskSpace.section),
              Text(
                curveLabel,
                style: const TextStyle(color: DeskColors.dim, fontSize: 10),
              ),
              const SizedBox(height: DeskSpace.section),
              SizedBox(
                height: 208,
                width: double.infinity,
                child: CustomPaint(
                  painter: _PnlCurvePainter(pnl.curve),
                  child: const SizedBox.expand(),
                ),
              ),
              const SizedBox(height: DeskSpace.section),
              for (var i = 0; i < exp.length; i++)
                _PnlMarkRow(exp[i].$1, exp[i].$2, zebra: i.isOdd),
            ],
          ),
        ),
      ),
      if (pnl.tape.isEmpty)
        const SliverToBoxAdapter(
          child: Padding(
            padding: EdgeInsets.fromLTRB(DeskSpace.inset, DeskSpace.section, DeskSpace.inset, 0),
            child: SizedBox(
              height: DeskSpace.row,
              child: Align(
                alignment: Alignment.centerLeft,
                child: Text('No tape — empty book.', style: TextStyle(color: DeskColors.muted, fontSize: 12)),
              ),
            ),
          ),
        )
      else
        SliverPadding(
          padding: DeskSpace.pageX,
          sliver: SliverList(
            delegate: SliverChildBuilderDelegate(
              (context, i) {
                final t = pnl.tape[i];
                return _PnlMarkRow(
                  t.symbol,
                  t.ready ? pct(t.dayPct) : '—',
                  zebra: i.isOdd,
                  valueColor: t.ready ? tone(t.dayPct) : DeskColors.muted,
                  onTap: () => onOpenChart(t.symbol),
                );
              },
              childCount: pnl.tape.length,
            ),
          ),
        ),
      if (pnl.message.isNotEmpty)
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(DeskSpace.inset, DeskSpace.section, DeskSpace.inset, 0),
            child: Text(pnl.message, style: const TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35)),
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

    String pct(double? v) => v == null ? '—' : '${v.toStringAsFixed(1)}%';
    final risk = pnl.risk;
    final rows = risk.names;
    final flags = <String>{
      ...pnl.alerts,
      for (final r in rows) ...r.flags,
    };
    Widget rowLine(String text, {Color color = DeskColors.text}) {
      return SizedBox(
        height: DeskSpace.row,
        width: double.infinity,
        child: Padding(
          padding: DeskSpace.cellPad,
          child: Align(
            alignment: Alignment.centerLeft,
            child: Text(
              text,
              maxLines: 1,
              softWrap: false,
              overflow: TextOverflow.ellipsis,
              style: TextStyle(color: color, fontSize: 12),
            ),
          ),
        ),
      );
    }

    return [
      SliverToBoxAdapter(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(DeskSpace.inset, DeskSpace.headerContent, DeskSpace.inset, 0),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            mainAxisSize: MainAxisSize.min,
            children: [
              if (rows.isEmpty)
                const Text(
                  'Thin or unmarked. Need ≥3 names, ≥60 overlapping daily closes, non-singular 60d Σ.',
                  style: TextStyle(color: DeskColors.muted, height: 1.4, fontSize: 12),
                )
              else ...[
                for (var i = 0; i < rows.length; i++)
                  GestureDetector(
                    onTap: () => onOpenChart(rows[i].symbol),
                    child: ColoredBox(
                      color: i.isOdd ? DeskColors.card : DeskColors.bg,
                      child: rowLine(
                        [
                          rows[i].symbol,
                          rows[i].weightPct == null ? 'w —' : 'w ${rows[i].weightPct!.toStringAsFixed(1)}%',
                          rows[i].vol20 == null ? 'σ20 —' : 'σ20 ${rows[i].vol20!.toStringAsFixed(0)}',
                          rows[i].vol60 == null ? 'σ60 —' : 'σ60 ${rows[i].vol60!.toStringAsFixed(0)}',
                          rows[i].betaSpy60 == null ? 'β —' : 'β ${rows[i].betaSpy60!.toStringAsFixed(2)}',
                          rows[i].mvar95 == null ? 'MVaR —' : 'MVaR ${usd(rows[i].mvar95)}',
                          rows[i].cvar95 == null ? 'CVaR —' : 'CVaR ${usd(rows[i].cvar95)}',
                          rows[i].pctVar == null ? '%VaR —' : '%VaR ${rows[i].pctVar!.toStringAsFixed(1)}',
                          if (rows[i].flags.isNotEmpty) rows[i].flags.join(' '),
                        ].join(' · '),
                      ),
                    ),
                  ),
                if (risk.clusters.isNotEmpty) ...[
                  const Text(
                    'Clusters',
                    style: TextStyle(fontWeight: FontWeight.w700, letterSpacing: 0.4, fontSize: 11, height: 1),
                  ),
                  for (final c in risk.clusters)
                    rowLine(
                      [
                        'C${c.id}',
                        c.members.join(' '),
                        c.regime.isEmpty ? '—' : c.regime,
                        c.pctVar == null ? '%VaR —' : '%VaR ${c.pctVar!.toStringAsFixed(1)}',
                      ].join(' · '),
                    ),
                ],
              ],
              Text(
                [
                  if (risk.ready) '${risk.nNames} names · ${risk.overlapDays}d',
                  if (risk.vol60 != null) 'σ60 ${risk.vol60!.toStringAsFixed(1)}%',
                  if (pnl.topWeightPct != null) 'top ${pnl.topWeightPct!.toStringAsFixed(0)}%',
                  ...flags,
                  'Hist ${pct(risk.hist95Pct)}/${pct(risk.hist99Pct)}',
                  'Param ${pct(risk.param95Pct)}/${pct(risk.param99Pct)}',
                  'Sharpe ${risk.sharpe?.toStringAsFixed(2) ?? '—'}',
                ].join(' · '),
                maxLines: 1,
                softWrap: false,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: DeskColors.muted, fontSize: 11),
              ),
              if (!risk.ready)
                Text(
                  risk.message.isEmpty ? 'Thin book — Risk stack blank.' : risk.message,
                  style: const TextStyle(color: DeskColors.muted, fontSize: 11, height: 1.35),
                ),
              const Offstage(child: Text('Ranked %VaR')),
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
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              const Text(
                'Fidelity: Positions → download CSV (Symbol + Quantity; Cost Basis Average optional). No login, no orders.',
                style: TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35),
              ),
              const SizedBox(height: 6),
              const Text(
                'Alpaca paper — not live P&L',
                style: TextStyle(color: DeskColors.muted, fontSize: 12),
              ),
              if (s.alpacaMessage != null && s.alpacaMessage!.isNotEmpty)
                Text(
                  s.alpacaMessage!,
                  style: const TextStyle(color: DeskColors.dim, fontSize: 11),
                ),
              Align(
                alignment: Alignment.centerLeft,
                child: CupertinoButton(
                  padding: const EdgeInsets.symmetric(horizontal: 0, vertical: 4),
                  onPressed: s.loadingBook ? null : s.syncAlpacaPaper,
                  child: const Text('Sync Alpaca paper', style: TextStyle(fontSize: 13)),
                ),
              ),
            ],
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
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          color: on ? DeskColors.accent.withValues(alpha: 0.2) : const Color(0x00000000),
          borderRadius: BorderRadius.zero,
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

class _PnlMarkRow extends StatelessWidget {
  const _PnlMarkRow(this.k, this.v, {this.zebra = false, this.valueColor, this.onTap});
  final String k;
  final String v;
  final bool zebra;
  final Color? valueColor;
  final VoidCallback? onTap;

  @override
  Widget build(BuildContext context) {
    final row = ColoredBox(
      color: zebra ? DeskColors.card : DeskColors.bg,
      child: SizedBox(
        height: DeskSpace.row,
        width: double.infinity,
        child: Padding(
          padding: DeskSpace.cellPad,
          child: Row(
            children: [
              Expanded(
                child: ClipRect(
                  child: Text(
                    k,
                    maxLines: 1,
                    softWrap: false,
                    overflow: TextOverflow.clip,
                    style: const TextStyle(color: DeskColors.text, fontSize: 12, fontWeight: FontWeight.w700),
                  ),
                ),
              ),
              Text(
                v,
                maxLines: 1,
                softWrap: false,
                style: TextStyle(
                  color: valueColor ?? DeskColors.text,
                  fontSize: 12,
                  fontFamily: 'Courier',
                ),
              ),
            ],
          ),
        ),
      ),
    );
    if (onTap == null) return row;
    return GestureDetector(onTap: onTap, child: row);
  }
}

/// Axis ticks come from stored daily marks only — no invented NAV or dates.
class _PnlCurvePainter extends CustomPainter {
  _PnlCurvePainter(this.marks);
  final List<(String, double)> marks;

  static String _dateTick(String raw) {
    final m = RegExp(r'^(\d{4})-(\d{2})-(\d{2})').firstMatch(raw);
    if (m != null) return '${m.group(2)}/${m.group(3)}';
    return raw.isEmpty ? '—' : raw;
  }

  static String _navTick(double v) {
    final abs = v.abs();
    final sign = v < 0 ? '−' : '';
    if (abs >= 10000) return '$sign\$${(abs / 1000).toStringAsFixed(1)}k';
    return '$sign\$${abs.toStringAsFixed(2)}';
  }

  static List<int> _tickIdx(int n) {
    if (n <= 0) return const [];
    if (n <= 4) return [for (var i = 0; i < n; i++) i];
    return {0, ((n - 1) / 3).round(), (2 * (n - 1) / 3).round(), n - 1}.toList()..sort();
  }

  void _label(Canvas canvas, String text, Offset at, {TextAlign align = TextAlign.left}) {
    final tp = TextPainter(
      text: TextSpan(
        text: text,
        style: const TextStyle(color: DeskColors.muted, fontSize: 9, fontFamily: 'Courier', height: 1),
      ),
      textDirection: TextDirection.ltr,
      textAlign: align,
      maxLines: 1,
    )..layout();
    var dx = at.dx;
    if (align == TextAlign.right) {
      dx -= tp.width;
    } else if (align == TextAlign.center) {
      dx -= tp.width / 2;
    }
    tp.paint(canvas, Offset(dx, at.dy));
  }

  @override
  void paint(Canvas canvas, Size size) {
    const left = 46.0;
    const right = 8.0;
    const top = 10.0;
    const bottom = 18.0;
    final plotW = size.width - left - right;
    final plotH = size.height - top - bottom;
    if (plotW <= 0 || plotH <= 0) return;

    if (marks.length < 2) {
      _label(canvas, 'No daily mark series — add lines and store Yahoo closes.', Offset(left, size.height / 2 - 5));
      return;
    }

    final vals = [for (final m in marks) m.$2];
    final minV = vals.reduce((a, b) => a < b ? a : b);
    final maxV = vals.reduce((a, b) => a > b ? a : b);
    final span = (maxV - minV).abs() < 1e-9 ? 1.0 : maxV - minV;

    Offset pt(int i) {
      final x = left + plotW * i / (vals.length - 1);
      final y = top + (1 - (vals[i] - minV) / span) * plotH;
      return Offset(x, y);
    }

    final grid = Paint()
      ..color = DeskColors.card
      ..strokeWidth = 1;

    var minI = 0;
    var maxI = 0;
    for (var i = 1; i < vals.length; i++) {
      if (vals[i] <= vals[minI]) minI = i;
      if (vals[i] >= vals[maxI]) maxI = i;
    }
    final yIdx = {minI, maxI, if (vals.length >= 3) vals.length ~/ 2};
    for (final i in yIdx) {
      final p = pt(i);
      canvas.drawLine(Offset(left, p.dy), Offset(left + plotW, p.dy), grid);
      _label(canvas, _navTick(vals[i]), Offset(left - 4, p.dy - 5), align: TextAlign.right);
    }

    for (final i in _tickIdx(marks.length)) {
      final p = pt(i);
      canvas.drawLine(Offset(p.dx, top), Offset(p.dx, top + plotH), grid);
      _label(canvas, _dateTick(marks[i].$1), Offset(p.dx, top + plotH + 3), align: TextAlign.center);
    }

    final open = vals.first;
    for (var i = 1; i < vals.length; i++) {
      final paint = Paint()
        ..color = vals[i] >= open ? DeskColors.green : DeskColors.red
        ..strokeWidth = 1.6
        ..style = PaintingStyle.stroke;
      canvas.drawLine(pt(i - 1), pt(i), paint);
    }
  }

  @override
  bool shouldRepaint(covariant _PnlCurvePainter old) => old.marks != marks;
}
