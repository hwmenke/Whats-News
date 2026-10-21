import 'dart:math' as math;

import 'package:flutter/widgets.dart';

import '../data/models.dart';
import 'theme.dart';

/// Interactive candlesticks + volume from stored OHLCV.
/// Overlays are Python `/api/indicators` series (KAMA / Bollinger) aligned by date.
class CandleChart extends StatefulWidget {
  const CandleChart({
    super.key,
    required this.bars,
    this.indicators = IndicatorPack.empty,
    this.showKama10 = false,
    this.showKama20 = true,
    this.showKama50 = false,
    this.showBollinger = false,
    this.showEma10 = false,
    this.showEma20 = false,
    this.onScrub,
  });

  final List<OhlcvBar> bars;
  final IndicatorPack indicators;
  final bool showKama10;
  final bool showKama20;
  final bool showKama50;
  final bool showBollinger;
  final bool showEma10;
  final bool showEma20;
  final ValueChanged<OhlcvBar?>? onScrub;

  @override
  State<CandleChart> createState() => _CandleChartState();
}

class _CandleChartState extends State<CandleChart> {
  late int _visible;
  int? _scrub;
  double _startVisible = 90;

  @override
  void initState() {
    super.initState();
    _visible = _defaultVisible(widget.bars.length);
  }

  @override
  void didUpdateWidget(covariant CandleChart oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.bars, widget.bars)) {
      _visible = _defaultVisible(widget.bars.length);
      _scrub = null;
    }
  }

  int _defaultVisible(int n) {
    if (n <= 0) return 0;
    return math.min(n, n > 160 ? 90 : n);
  }

  void _setScrub(int? i) {
    if (_scrub == i) return;
    setState(() => _scrub = i);
    if (i == null) {
      widget.onScrub?.call(null);
    } else {
      final start = widget.bars.length - _visible;
      final idx = start + i;
      if (idx >= 0 && idx < widget.bars.length) {
        widget.onScrub?.call(widget.bars[idx]);
      }
    }
  }

  void _handleScale(ScaleUpdateDetails d, double width) {
    if (widget.bars.isEmpty) return;
    if ((d.scale - 1.0).abs() > 0.04) {
      final next = (_startVisible / d.scale).round().clamp(20, widget.bars.length);
      if (next != _visible) {
        setState(() => _visible = next);
      }
      return;
    }
    _scrubAtX(d.localFocalPoint.dx, width);
  }

  void _scrubAtX(double x, double width) {
    if (widget.bars.isEmpty || width <= 0) return;
    final plotW = width - _CandlePainter.labelGutter;
    final slot = plotW / _visible;
    final i = (x / slot).floor().clamp(0, _visible - 1);
    _setScrub(i);
  }

  @override
  Widget build(BuildContext context) {
    if (widget.bars.isEmpty) {
      return const Center(
        child: Text(
          'No stored bars',
          style: TextStyle(color: DeskColors.muted),
        ),
      );
    }
    final start = widget.bars.length - _visible;
    final window = widget.bars.sublist(start);
    return GestureDetector(
      onScaleStart: (d) {
        _startVisible = _visible.toDouble();
      },
      onScaleUpdate: (d) {
        final box = context.findRenderObject() as RenderBox?;
        _handleScale(d, box?.size.width ?? 0);
      },
      onTapUp: (d) => _scrubAtX(d.localPosition.dx, context.size?.width ?? 0),
      onDoubleTap: () {
        setState(() {
          _visible = _defaultVisible(widget.bars.length);
          _scrub = null;
        });
        widget.onScrub?.call(null);
      },
      child: CustomPaint(
        painter: _CandlePainter(
          bars: window,
          fullCount: widget.bars.length,
          indicators: widget.indicators,
          showKama10: widget.showKama10,
          showKama20: widget.showKama20,
          showKama50: widget.showKama50,
          showBollinger: widget.showBollinger,
          showEma10: widget.showEma10,
          showEma20: widget.showEma20,
          scrub: _scrub,
        ),
        child: const SizedBox.expand(),
      ),
    );
  }
}

class _CandlePainter extends CustomPainter {
  _CandlePainter({
    required this.bars,
    required this.fullCount,
    required this.indicators,
    required this.showKama10,
    required this.showKama20,
    required this.showKama50,
    required this.showBollinger,
    required this.showEma10,
    required this.showEma20,
    required this.scrub,
  });

  final List<OhlcvBar> bars;
  final int fullCount;
  final IndicatorPack indicators;
  final bool showKama10;
  final bool showKama20;
  final bool showKama50;
  final bool showBollinger;
  final bool showEma10;
  final bool showEma20;
  final int? scrub;

  static const labelGutter = 46.0;
  static const volFrac = 0.22;

  @override
  void paint(Canvas canvas, Size size) {
    if (bars.isEmpty || size.width <= 0 || size.height <= 0) return;

    final plotW = size.width - labelGutter;
    final volH = size.height * volFrac;
    final priceH = size.height - volH - 16;
    var minP = bars.first.low;
    var maxP = bars.first.high;
    var maxV = 0.0;
    for (final b in bars) {
      minP = math.min(minP, b.low);
      maxP = math.max(maxP, b.high);
      maxV = math.max(maxV, b.volume);
    }
    void includeSeries(List<IndicatorPoint> pts) {
      final dates = {for (final b in bars) b.date};
      for (final p in pts) {
        if (p.value == null || !dates.contains(p.date)) continue;
        minP = math.min(minP, p.value!);
        maxP = math.max(maxP, p.value!);
      }
    }

    if (showKama10) includeSeries(indicators.of('kama_10'));
    if (showKama20) includeSeries(indicators.of('kama_20'));
    if (showKama50) includeSeries(indicators.of('kama_50'));
    if (showEma10) includeSeries(indicators.of('ema_10'));
    if (showEma20) includeSeries(indicators.of('ema_20'));
    if (showBollinger) {
      includeSeries(indicators.of('bb_upper'));
      includeSeries(indicators.of('bb_lower'));
    }

    if (maxP <= minP) {
      maxP = minP + 1;
    }
    final pad = (maxP - minP) * 0.04;
    minP -= pad;
    maxP += pad;
    final range = maxP - minP;
    final slot = plotW / bars.length;
    final bodyW = math.max(1.0, slot * 0.62);

    final grid = Paint()
      ..color = DeskColors.border.withValues(alpha: 0.55)
      ..strokeWidth = 1;
    final labelStyle = const TextStyle(color: DeskColors.muted, fontSize: 10);

    for (var i = 0; i <= 4; i++) {
      final y = priceH * i / 4;
      canvas.drawLine(Offset(0, y), Offset(plotW, y), grid);
      final price = maxP - (maxP - minP) * i / 4;
      _label(
        canvas,
        _fmt(price),
        Offset(plotW + 4, math.max(0, y - 6)),
        labelStyle,
      );
    }

    if (showBollinger) {
      _polyline(canvas, indicators.of('bb_upper'), bars, minP, range, priceH, plotW,
          DeskColors.dim, dashed: true);
      _polyline(canvas, indicators.of('bb_middle'), bars, minP, range, priceH, plotW,
          DeskColors.muted);
      _polyline(canvas, indicators.of('bb_lower'), bars, minP, range, priceH, plotW,
          DeskColors.dim, dashed: true);
    }
    if (showKama50) {
      _polyline(canvas, indicators.of('kama_50'), bars, minP, range, priceH, plotW,
          DeskColors.kama50);
    }
    if (showKama20) {
      _polyline(canvas, indicators.of('kama_20'), bars, minP, range, priceH, plotW,
          DeskColors.kama20);
    }
    if (showKama10) {
      _polyline(canvas, indicators.of('kama_10'), bars, minP, range, priceH, plotW,
          DeskColors.kama10);
    }
    if (showEma10) {
      _polyline(canvas, indicators.of('ema_10'), bars, minP, range, priceH, plotW,
          DeskColors.ema10);
    }
    if (showEma20) {
      _polyline(canvas, indicators.of('ema_20'), bars, minP, range, priceH, plotW,
          DeskColors.ema20);
    }

    for (var i = 0; i < bars.length; i++) {
      final b = bars[i];
      final x = slot * i + slot / 2;
      final up = b.close >= b.open;
      final color = up ? DeskColors.green : DeskColors.red;
      final wick = Paint()
        ..color = color
        ..strokeWidth = 1;
      final body = Paint()..color = color;
      final yHigh = _y(b.high, minP, range, priceH);
      final yLow = _y(b.low, minP, range, priceH);
      final yOpen = _y(b.open, minP, range, priceH);
      final yClose = _y(b.close, minP, range, priceH);
      canvas.drawLine(Offset(x, yHigh), Offset(x, yLow), wick);
      final top = math.min(yOpen, yClose);
      final h = math.max(1.0, (yOpen - yClose).abs());
      canvas.drawRect(
        Rect.fromCenter(center: Offset(x, top + h / 2), width: bodyW, height: h),
        body,
      );

      if (maxV > 0 && volH > 0) {
        final vh = (b.volume / maxV) * (volH - 4);
        canvas.drawRect(
          Rect.fromLTWH(x - bodyW / 2, size.height - vh, bodyW, vh),
          Paint()..color = color.withValues(alpha: 0.45),
        );
      }
    }

    canvas.drawLine(Offset(0, priceH + 4), Offset(plotW, priceH + 4), grid);
    _label(canvas, 'Vol ${_fmtVol(maxV)}', Offset(6, priceH + 6), labelStyle);
    _label(canvas, bars.first.date, Offset(6, size.height - 13), labelStyle);
    final endTp = TextPainter(
      text: TextSpan(text: bars.last.date, style: labelStyle),
      textDirection: TextDirection.ltr,
    )..layout();
    endTp.paint(canvas, Offset(math.max(6, plotW - endTp.width - 4), size.height - 13));

    if (fullCount > bars.length) {
      _label(
        canvas,
        '${bars.length}/$fullCount  pinch zoom · drag OHLC',
        Offset(6, 4),
        const TextStyle(color: DeskColors.dim, fontSize: 9),
      );
    }

    if (scrub != null && scrub! >= 0 && scrub! < bars.length) {
      final x = slot * scrub! + slot / 2;
      final hair = Paint()
        ..color = DeskColors.accentBright.withValues(alpha: 0.85)
        ..strokeWidth = 1;
      canvas.drawLine(Offset(x, 0), Offset(x, size.height), hair);
      final b = bars[scrub!];
      _label(
        canvas,
        b.date,
        Offset((x + 4).clamp(4, plotW - 72), priceH - 14),
        const TextStyle(color: DeskColors.accentBright, fontSize: 10),
      );
    }
  }

  void _polyline(
    Canvas canvas,
    List<IndicatorPoint> pts,
    List<OhlcvBar> bars,
    double minP,
    double range,
    double priceH,
    double plotW,
    Color color, {
    bool dashed = false,
  }) {
    if (pts.isEmpty) return;
    final byDate = {for (final p in pts) p.date: p.value};
    final slot = plotW / bars.length;
    final path = Path();
    var started = false;
    for (var i = 0; i < bars.length; i++) {
      final v = byDate[bars[i].date];
      if (v == null) continue;
      final x = slot * i + slot / 2;
      final y = _y(v, minP, range, priceH);
      if (!started) {
        path.moveTo(x, y);
        started = true;
      } else {
        path.lineTo(x, y);
      }
    }
    if (!started) return;
    final paint = Paint()
      ..color = color
      ..style = PaintingStyle.stroke
      ..strokeWidth = 1.2;
    if (dashed) {
      _dash(canvas, path, paint);
    } else {
      canvas.drawPath(path, paint);
    }
  }

  void _dash(Canvas canvas, Path path, Paint paint) {
    for (final metric in path.computeMetrics()) {
      var d = 0.0;
      while (d < metric.length) {
        final next = math.min(d + 4, metric.length);
        canvas.drawPath(metric.extractPath(d, next), paint);
        d += 8;
      }
    }
  }

  double _y(double price, double minP, double range, double height) {
    return height - ((price - minP) / range) * height;
  }

  String _fmt(double v) {
    if (v >= 1000) return v.toStringAsFixed(0);
    if (v >= 100) return v.toStringAsFixed(1);
    return v.toStringAsFixed(2);
  }

  String _fmtVol(double v) {
    if (v >= 1e9) return '${(v / 1e9).toStringAsFixed(1)}B';
    if (v >= 1e6) return '${(v / 1e6).toStringAsFixed(1)}M';
    if (v >= 1e3) return '${(v / 1e3).toStringAsFixed(0)}K';
    return v.toStringAsFixed(0);
  }

  void _label(Canvas canvas, String text, Offset offset, TextStyle style) {
    final tp = TextPainter(
      text: TextSpan(text: text, style: style),
      textDirection: TextDirection.ltr,
    )..layout();
    tp.paint(canvas, offset);
  }

  @override
  bool shouldRepaint(covariant _CandlePainter oldDelegate) =>
      !identical(oldDelegate.bars, bars) ||
      oldDelegate.scrub != scrub ||
      oldDelegate.showKama10 != showKama10 ||
      oldDelegate.showKama20 != showKama20 ||
      oldDelegate.showKama50 != showKama50 ||
      oldDelegate.showBollinger != showBollinger ||
      oldDelegate.showEma10 != showEma10 ||
      oldDelegate.showEma20 != showEma20 ||
      !identical(oldDelegate.indicators, indicators);
}
