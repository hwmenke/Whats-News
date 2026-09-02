import 'dart:math' as math;

import 'package:flutter/widgets.dart';

import '../data/models.dart';
import 'theme.dart';

/// Daily/weekly candlesticks + volume — drawn locally from stored OHLCV.
class CandleChart extends StatelessWidget {
  const CandleChart({super.key, required this.bars});

  final List<OhlcvBar> bars;

  @override
  Widget build(BuildContext context) {
    if (bars.isEmpty) {
      return const Center(
        child: Text(
          'No bars yet',
          style: TextStyle(color: DeskColors.muted),
        ),
      );
    }
    return CustomPaint(
      painter: _CandlePainter(bars),
      child: const SizedBox.expand(),
    );
  }
}

class _CandlePainter extends CustomPainter {
  _CandlePainter(this.bars);

  final List<OhlcvBar> bars;

  @override
  void paint(Canvas canvas, Size size) {
    if (bars.isEmpty || size.width <= 0 || size.height <= 0) return;

    const volFrac = 0.18;
    final volH = size.height * volFrac;
    final priceH = size.height - volH - 8;
    var minP = bars.first.low;
    var maxP = bars.first.high;
    var maxV = 0.0;
    for (final b in bars) {
      minP = math.min(minP, b.low);
      maxP = math.max(maxP, b.high);
      maxV = math.max(maxV, b.volume);
    }
    if (maxP <= minP) {
      maxP = minP + 1;
    }
    final pad = (maxP - minP) * 0.04;
    minP -= pad;
    maxP += pad;
    final range = maxP - minP;
    final slot = size.width / bars.length;
    final bodyW = math.max(1.0, slot * 0.62);

    final grid = Paint()
      ..color = DeskColors.border.withValues(alpha: 0.45)
      ..strokeWidth = 1;
    for (var i = 1; i <= 3; i++) {
      final y = priceH * i / 4;
      canvas.drawLine(Offset(0, y), Offset(size.width, y), grid);
    }

    final labelStyle = const TextStyle(
      color: DeskColors.muted,
      fontSize: 10,
    );
    _label(canvas, _fmt(maxP), const Offset(6, 4), labelStyle);
    _label(canvas, _fmt(minP), Offset(6, priceH - 14), labelStyle);

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
        final vh = (b.volume / maxV) * (volH - 2);
        canvas.drawRect(
          Rect.fromLTWH(
            x - bodyW / 2,
            size.height - vh,
            bodyW,
            vh,
          ),
          Paint()..color = color.withValues(alpha: 0.35),
        );
      }
    }

    // Divider between price and volume.
    canvas.drawLine(
      Offset(0, priceH + 4),
      Offset(size.width, priceH + 4),
      grid,
    );
  }

  double _y(double price, double minP, double range, double height) {
    return height - ((price - minP) / range) * height;
  }

  String _fmt(double v) {
    if (v >= 1000) return v.toStringAsFixed(0);
    if (v >= 100) return v.toStringAsFixed(1);
    return v.toStringAsFixed(2);
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
      !identical(oldDelegate.bars, bars);
}
