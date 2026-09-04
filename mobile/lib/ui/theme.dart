import 'package:flutter/cupertino.dart';

/// Desk palette — functional desk, not a final Visual UX pack.
/// HOLD: neon rejected; cream-paper v2 (#F4F2EC / serif 538) rejected.
/// Do not implement v3 Obsidian/Mint here. Web faces: styles/theme.css.
class DeskColors {
  static const bg = Color(0xFF0D1117);
  static const elevated = Color(0xFF161B22);
  static const card = Color(0xFF1C2230);
  static const hover = Color(0xFF242B3D);
  static const border = Color(0xFF30363D);
  static const accent = Color(0xFF3B82F6);
  static const accentBright = Color(0xFF60A5FA);
  static const green = Color(0xFF22C55E);
  static const red = Color(0xFFEF4444);
  static const yellow = Color(0xFFEAB308);
  static const cyan = Color(0xFF06B6D4);
  static const orange = Color(0xFFF97316);
  static const purple = Color(0xFFA855F7);
  static const text = Color(0xFFE6EDF3);
  static const muted = Color(0xFF8B949E);
  static const dim = Color(0xFF4A5568);
  static const kama10 = Color(0xFF60A5FA);
  static const kama20 = Color(0xFFF59E0B);
  static const kama50 = Color(0xFFA78BFA);
  static const ema10 = Color(0xFF34D399);
  static const ema20 = Color(0xFFF472B6);
}

CupertinoThemeData deskCupertinoTheme() {
  return const CupertinoThemeData(
    brightness: Brightness.dark,
    primaryColor: DeskColors.accentBright,
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
