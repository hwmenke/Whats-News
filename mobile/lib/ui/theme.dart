import 'package:flutter/cupertino.dart';

/// VISUAL v2 — Ex Ante × FiveThirtyEight. Discard dark neon HUD.
/// Paper / ink / coral↔blue-gray. Comp AAA rows are not live data.
/// Web faces live in `styles/theme.css` (Source Serif 4 + Inter + mono).
class DeskColors {
  static const bg = Color(0xFFF4F2EC);
  static const elevated = Color(0xFFFFFFFF);
  static const card = Color(0xFFFFFFFF);
  static const hover = Color(0xFFEFECE4);
  static const border = Color(0xFFE7E5E0);
  static const accent = Color(0xFF1C1917);
  static const accentBright = Color(0xFF1C1917);
  static const green = Color(0xFF3F6F6A);
  static const red = Color(0xFFB4532A);
  static const yellow = Color(0xFF7C5A1E);
  static const cyan = Color(0xFF7A9AA8);
  static const orange = Color(0xFFD97757);
  static const purple = Color(0xFF6B5B8C);
  static const text = Color(0xFF1C1917);
  static const muted = Color(0xFF57534E);
  static const dim = Color(0xFFA8A29E);
  static const kama10 = Color(0xFF7A9AA8);
  static const kama20 = Color(0xFFD97757);
  static const kama50 = Color(0xFF6B5B8C);
  static const ema10 = Color(0xFF3F6F6A);
  static const ema20 = Color(0xFFB4532A);
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
