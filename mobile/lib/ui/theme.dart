import 'package:flutter/cupertino.dart';

/// VISUAL v3 — Obsidian / Paper / Mint surface-only.
/// Discard cream v2 and dark neon. Comp AAA rows are not live data.
/// Web faces: Fraunces / Inter / IBM Plex Mono stand in for
/// Alliance No.2 + Geist + Geist Mono (`styles/theme.css`).
class DeskColors {
  static const bg = Color(0xFFFFFFFF);
  static const elevated = Color(0xFFFFFFFF);
  static const card = Color(0xFFFFFFFF);
  static const hover = Color(0xFFF4F4F3);
  static const border = Color(0xFF1E211E);
  static const accent = Color(0xFF1E211E);
  static const accentBright = Color(0xFF1E211E);
  static const green = Color(0xFF90FC95); // mint — surface only
  static const red = Color(0xFF1E211E);
  static const yellow = Color(0xFF4B4D4B);
  static const cyan = Color(0xFF4B4D4B);
  static const orange = Color(0xFF4B4D4B);
  static const purple = Color(0xFF4B4D4B);
  static const text = Color(0xFF1E211E);
  static const muted = Color(0xFF4B4D4B);
  static const dim = Color(0xFFD2D3D2);
  static const kama10 = Color(0xFF1E211E);
  static const kama20 = Color(0xFF4B4D4B);
  static const kama50 = Color(0xFFD2D3D2);
  static const ema10 = Color(0xFF90FC95);
  static const ema20 = Color(0xFF1E211E);
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
