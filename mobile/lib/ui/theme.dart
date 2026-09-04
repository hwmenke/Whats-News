import 'package:flutter/cupertino.dart';

/// Desk palette — same colors as the Dash `styles/main.css` dark theme.
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
