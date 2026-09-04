import 'package:flutter/cupertino.dart';

/// VISUAL v4.1 — Ink #111, zebra/fills, no borders.
/// Mint ≤1 OPPORTUNITY fill. Soft R/G heat. Discard neon/cream/v3.
/// Web faces: IBM Plex Sans Condensed + Inter + IBM Plex Mono (`styles/theme.css`).
/// Market Moves stays utilitarian red/green z heat.
class DeskColors {
  static const bg = Color(0xFFFFFFFF);
  static const elevated = Color(0xFFFFFFFF);
  static const card = Color(0xFFF3F3F3);
  static const hover = Color(0xFFF3F3F3);
  static const border = Color(0x00000000);
  static const accent = Color(0xFF111111);
  static const accentBright = Color(0xFF111111);
  static const green = Color(0xFF22C55E);
  static const red = Color(0xFFEF4444);
  static const yellow = Color(0xFF111111);
  static const cyan = Color(0xFF0F766E);
  static const orange = Color(0xFFE07A5F);
  static const purple = Color(0xFF111111);
  static const text = Color(0xFF111111);
  static const muted = Color(0xFF666666);
  static const dim = Color(0xFF999999);
  static const kama10 = Color(0xFF0F766E);
  static const kama20 = Color(0xFFE07A5F);
  static const kama50 = Color(0xFF111111);
  static const ema10 = Color(0xFF22C55E);
  static const ema20 = Color(0xFFEF4444);
}

CupertinoThemeData deskCupertinoTheme() {
  return const CupertinoThemeData(
    brightness: Brightness.light,
    primaryColor: DeskColors.accent,
    scaffoldBackgroundColor: DeskColors.bg,
    barBackgroundColor: DeskColors.elevated,
    textTheme: CupertinoTextThemeData(
      textStyle: TextStyle(
        fontFamily: '.SF Pro Text',
        color: DeskColors.text,
        fontSize: 16,
      ),
    ),
  );
}
