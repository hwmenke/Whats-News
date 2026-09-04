/// Shared models for the Whats-News client.
///
/// These match the JSON from the Python data layer (`/api/symbols`,
/// `/api/ohlcv/<sym>`, `/api/news`) used by the Dash app.
library;

class WatchSymbol {
  const WatchSymbol({
    required this.symbol,
    this.name = '',
    this.sector = '',
    this.groupTag = '',
    this.filterKind = '',
    this.groupLabel = '',
  });

  final String symbol;
  final String name;
  final String sector;
  final String groupTag;
  final String filterKind;
  final String groupLabel;

  bool get isUniverseArchive => groupTag.startsWith('univ:');

  String get filterFamily {
    if (filterKind.isNotEmpty) return filterKind;
    final tag = groupTag.toLowerCase();
    if (tag.contains('countries') || tag.contains('intl')) return 'country';
    if (tag.contains('sector')) return 'sector';
    if (tag.contains('theme') ||
        tag.contains('tech') ||
        tag.contains('resource') ||
        tag.contains('crypto') ||
        tag.contains('bond') ||
        tag.contains('ags') ||
        tag.contains('metal') ||
        tag.contains('fx') ||
        tag.contains('yield') ||
        tag.contains('big_tech') ||
        tag.contains('commodit') ||
        tag.contains('rates')) {
      return 'theme';
    }
    if (tag.contains('index') || tag == 'sleeve:core' || tag.contains('broad_etf')) {
      return 'index';
    }
    return '';
  }

  String get displayGroup {
    if (groupLabel.isNotEmpty) return groupLabel;
    if (groupTag.isEmpty) return 'Ungrouped';
    return groupTag;
  }

  factory WatchSymbol.fromJson(Map<String, dynamic> json) {
    return WatchSymbol(
      symbol: (json['symbol'] as String? ?? '').toUpperCase(),
      name: json['name'] as String? ?? '',
      sector: json['sector'] as String? ?? '',
      groupTag: json['group_tag'] as String? ?? '',
      filterKind: '${json['filter_kind'] ?? ''}',
      groupLabel: '${json['group_label'] ?? ''}',
    );
  }
}

class OhlcvBar {
  const OhlcvBar({
    required this.date,
    required this.open,
    required this.high,
    required this.low,
    required this.close,
    required this.volume,
  });

  final String date;
  final double open;
  final double high;
  final double low;
  final double close;
  final double volume;

  bool get isUp => close >= open;

  factory OhlcvBar.fromJson(Map<String, dynamic> json) {
    double n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v') ?? 0;
    }

    return OhlcvBar(
      date: '${json['date'] ?? ''}',
      open: n(json['open']),
      high: n(json['high']),
      low: n(json['low']),
      close: n(json['close']),
      volume: n(json['volume']),
    );
  }
}

class NewsArticle {
  const NewsArticle({
    required this.title,
    required this.url,
    this.symbol,
    this.summary = '',
    this.publishTime = '',
    this.provider = 'Yahoo Finance',
    this.providerUrl = 'https://finance.yahoo.com/',
  });

  final String title;
  final String url;
  final String? symbol;
  final String summary;
  final String publishTime;
  final String provider;
  final String providerUrl;

  factory NewsArticle.fromJson(Map<String, dynamic> json) {
    final symbol = json['symbol'] as String?;
    return NewsArticle(
      title: json['title'] as String? ?? 'No title',
      url: json['url'] as String? ?? '',
      symbol: symbol == null || symbol.isEmpty ? null : symbol.toUpperCase(),
      summary: json['summary'] as String? ?? '',
      publishTime: json['publish_time'] as String? ?? '',
      provider: json['provider'] as String? ?? 'Yahoo Finance',
      providerUrl: json['provider_url'] as String? ?? 'https://finance.yahoo.com/',
    );
  }
}

class NewsFeed {
  const NewsFeed({
    required this.articles,
    this.source = 'Yahoo Finance',
    this.message,
    this.errors = const [],
  });

  final List<NewsArticle> articles;
  final String source;
  final String? message;
  final List<String> errors;

  factory NewsFeed.fromJson(Map<String, dynamic> json) {
    final raw = json['articles'];
    final articles = <NewsArticle>[];
    if (raw is List) {
      for (final item in raw) {
        if (item is Map<String, dynamic>) {
          articles.add(NewsArticle.fromJson(item));
        } else if (item is Map) {
          articles.add(NewsArticle.fromJson(Map<String, dynamic>.from(item)));
        }
      }
    }
    final errRaw = json['errors'];
    final errors = <String>[];
    if (errRaw is List) {
      for (final e in errRaw) {
        if (e is Map && e['error'] != null) {
          errors.add('${e['symbol'] ?? '?'}: ${e['error']}');
        }
      }
    }
    return NewsFeed(
      articles: articles,
      source: json['source'] as String? ?? 'Yahoo Finance',
      message: json['message'] as String?,
      errors: errors,
    );
  }
}

class ApiException implements Exception {
  ApiException(this.message, {this.status, this.code, this.retryAfterSec});

  final String message;
  final int? status;
  final String? code;
  final int? retryAfterSec;

  bool get isThrottle => code == 'yahoo_throttle' || status == 429;

  bool get isMissingBars => status == 404;

  @override
  String toString() => message;
}

class IndicatorPoint {
  const IndicatorPoint({required this.date, this.value});

  final String date;
  final double? value;

  factory IndicatorPoint.fromJson(Map<String, dynamic> json) {
    final raw = json['value'];
    double? v;
    if (raw is num) {
      v = raw.toDouble();
    } else if (raw != null) {
      v = double.tryParse('$raw');
    }
    return IndicatorPoint(date: '${json['date'] ?? ''}', value: v);
  }
}

/// Series from GET /api/indicators — KAMA / BB / RSI computed in Python.
class IndicatorPack {
  const IndicatorPack({this.series = const {}});

  final Map<String, List<IndicatorPoint>> series;

  static const empty = IndicatorPack();

  List<IndicatorPoint> of(String key) => series[key] ?? const [];

  factory IndicatorPack.fromJson(Map<String, dynamic> json) {
    if (json['error'] != null) return empty;
    final out = <String, List<IndicatorPoint>>{};
    json.forEach((key, raw) {
      if (raw is! List) return;
      out[key] = [
        for (final item in raw)
          if (item is Map)
            IndicatorPoint.fromJson(Map<String, dynamic>.from(item)),
      ];
    });
    return IndicatorPack(series: out);
  }
}

class TrendScanRow {
  const TrendScanRow({
    required this.symbol,
    this.price,
    this.rsi,
    this.kama10Pct,
    this.kama20Pct,
    this.kama50Pct,
    this.signal,
    this.rr,
    this.mrt,
    this.mdb,
    this.error,
  });

  final String symbol;
  final double? price;
  final double? rsi;
  final double? kama10Pct;
  final double? kama20Pct;
  final double? kama50Pct;
  final int? signal;
  final double? rr;
  final double? mrt;
  final double? mdb;
  final String? error;

  factory TrendScanRow.fromJson(Map<String, dynamic> json) {
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    int? i(Object? v) {
      if (v is int) return v;
      if (v is num) return v.toInt();
      return int.tryParse('$v');
    }

    return TrendScanRow(
      symbol: (json['symbol'] as String? ?? '').toUpperCase(),
      price: n(json['price']),
      rsi: n(json['rsi']),
      kama10Pct: n(json['kama10_pct']),
      kama20Pct: n(json['kama20_pct']),
      kama50Pct: n(json['kama50_pct']),
      signal: i(json['signal']),
      rr: n(json['rr']),
      mrt: n(json['mrt']),
      mdb: n(json['mdb']),
      error: json['error'] as String?,
    );
  }
}

class ScannerTf {
  const ScannerTf({
    this.rsi14,
    this.atrPct,
    this.roc1m,
    this.volRatio,
    this.distHi,
    this.distSma,
    this.trendScore,
    this.pKfPct,
  });

  final double? rsi14;
  final double? atrPct;
  final double? roc1m;
  final double? volRatio;
  final double? distHi;
  final double? distSma;
  final double? trendScore;
  final double? pKfPct;

  factory ScannerTf.fromJson(Map<String, dynamic>? json) {
    if (json == null) return const ScannerTf();
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    return ScannerTf(
      rsi14: n(json['rsi_14']),
      atrPct: n(json['atr_pct']),
      roc1m: n(json['roc_1m']),
      volRatio: n(json['vol_ratio']),
      distHi: n(json['dist_hi']),
      distSma: n(json['dist_sma']),
      trendScore: n(json['trend_score']),
      pKfPct: n(json['p_kf_pct']),
    );
  }
}

class ScannerRow {
  const ScannerRow({
    required this.symbol,
    this.price,
    this.chg,
    this.error,
    this.daily = const ScannerTf(),
  });

  final String symbol;
  final double? price;
  final double? chg;
  final String? error;
  final ScannerTf daily;

  factory ScannerRow.fromJson(Map<String, dynamic> json) {
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    Map<String, dynamic>? tf;
    final raw = json['d'];
    if (raw is Map) tf = Map<String, dynamic>.from(raw);

    return ScannerRow(
      symbol: (json['symbol'] as String? ?? '').toUpperCase(),
      price: n(json['price']),
      chg: n(json['chg']),
      error: json['error'] as String?,
      daily: ScannerTf.fromJson(tf),
    );
  }
}

class SetupScanRow {
  const SetupScanRow({
    required this.symbol,
    this.ready = false,
    this.price,
    this.changePct,
    this.setups = const [],
    this.setupScore,
    this.adrPct,
    this.regime,
    this.dist20dHighPct,
    this.volRatio,
    this.gapPct,
    this.error,
  });

  final String symbol;
  final bool ready;
  final double? price;
  final double? changePct;
  final List<String> setups;
  final double? setupScore;
  final double? adrPct;
  final String? regime;
  final double? dist20dHighPct;
  final double? volRatio;
  final double? gapPct;
  final String? error;

  /// Desk heuristic — high-ADR names (not a published rating).
  bool get isHighAdr => adrPct != null && adrPct! >= 4.0;

  bool get isEp => setups.contains('EP');
  bool get isBreakoutQueue => setups.contains('BREAKOUT_QUEUE');
  bool get isVolSurge => setups.contains('VOL_SURGE');
  bool get isNearHigh => setups.contains('NEAR_HIGH');

  bool get isQullaCandidate =>
      isEp || isBreakoutQueue || isVolSurge || setups.contains('NEAR_HIGH') || isHighAdr;

  factory SetupScanRow.fromJson(Map<String, dynamic> json) {
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    final rawSetups = json['setups'];
    final setups = <String>[];
    if (rawSetups is List) {
      for (final s in rawSetups) {
        if (s != null && '$s'.isNotEmpty) setups.add('$s');
      }
    }
    return SetupScanRow(
      symbol: (json['symbol'] as String? ?? '').toUpperCase(),
      ready: json['ready'] == true,
      price: n(json['price']),
      changePct: n(json['change_pct']),
      setups: setups,
      setupScore: n(json['setup_score']),
      adrPct: n(json['adr_pct']),
      regime: json['regime'] as String?,
      dist20dHighPct: n(json['dist_20d_high_pct']),
      volRatio: n(json['vol_ratio_5_20']),
      gapPct: n(json['gap_pct']),
      error: json['error'] as String?,
    );
  }
}

class Sleeve {
  const Sleeve({
    required this.id,
    required this.label,
    required this.groupTag,
    this.blurb = '',
    this.tickers = const [],
    this.filterKind = '',
    this.skipped = '',
  });

  final String id;
  final String label;
  final String groupTag;
  final String blurb;
  final List<String> tickers;
  final String filterKind;
  final String skipped;

  factory Sleeve.fromJson(Map<String, dynamic> json) {
    final raw = json['tickers'];
    return Sleeve(
      id: '${json['id'] ?? ''}',
      label: '${json['label'] ?? ''}',
      groupTag: '${json['group_tag'] ?? ''}',
      blurb: '${json['blurb'] ?? ''}',
      filterKind: '${json['filter_kind'] ?? ''}',
      skipped: '${json['skipped'] ?? ''}',
      tickers: [
        if (raw is List)
          for (final t in raw)
            if (t != null && '$t'.trim().isNotEmpty) '$t'.trim().toUpperCase(),
      ],
    );
  }
}

class VolRegime {
  const VolRegime({
    this.ready = false,
    this.symbol = '',
    this.vix,
    this.percentile1y,
    this.label = '',
    this.note = '',
  });

  final bool ready;
  final String symbol;
  final double? vix;
  final int? percentile1y;
  final String label;
  final String note;

  static const empty = VolRegime();

  factory VolRegime.fromJson(Map<String, dynamic>? json) {
    if (json == null) return empty;
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    return VolRegime(
      ready: json['ready'] == true,
      symbol: '${json['symbol'] ?? ''}',
      vix: n(json['vix']),
      percentile1y: json['percentile_1y'] is num
          ? (json['percentile_1y'] as num).toInt()
          : int.tryParse('${json['percentile_1y'] ?? ''}'),
      label: '${json['label'] ?? ''}',
      note: '${json['note'] ?? ''}',
    );
  }
}

class MacroMoveRow {
  const MacroMoveRow({
    required this.symbol,
    this.ready = false,
    this.px,
    this.dayPct,
    this.z30,
    this.z14,
    this.extreme = false,
  });

  final String symbol;
  final bool ready;
  final double? px;
  final double? dayPct;
  final double? z30;
  final double? z14;
  final bool extreme;

  factory MacroMoveRow.fromJson(Map<String, dynamic> json) {
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    return MacroMoveRow(
      symbol: (json['symbol'] as String? ?? '').toUpperCase(),
      ready: json['ready'] == true,
      px: n(json['px']),
      dayPct: n(json['day_pct']),
      z30: n(json['z30']),
      z14: n(json['z14']),
      extreme: json['extreme'] == true,
    );
  }
}

class MacroSleeveBlock {
  const MacroSleeveBlock({
    required this.id,
    required this.label,
    this.groupTag = '',
    this.filterKind = '',
    this.blurb = '',
    this.skipped = '',
    this.tickers = const [],
    this.readyCount = 0,
    this.rows = const [],
  });

  final String id;
  final String label;
  final String groupTag;
  final String filterKind;
  final String blurb;
  final String skipped;
  final List<String> tickers;
  final int readyCount;
  final List<MacroMoveRow> rows;

  factory MacroSleeveBlock.fromJson(Map<String, dynamic> json) {
    final rawT = json['tickers'];
    final rawR = json['rows'];
    return MacroSleeveBlock(
      id: '${json['id'] ?? ''}',
      label: '${json['label'] ?? ''}',
      groupTag: '${json['group_tag'] ?? ''}',
      filterKind: '${json['filter_kind'] ?? ''}',
      blurb: '${json['blurb'] ?? ''}',
      skipped: '${json['skipped'] ?? ''}',
      tickers: [
        if (rawT is List)
          for (final t in rawT)
            if (t != null && '$t'.trim().isNotEmpty) '$t'.trim().toUpperCase(),
      ],
      readyCount: json['ready_count'] is num ? (json['ready_count'] as num).toInt() : 0,
      rows: [
        if (rawR is List)
          for (final item in rawR)
            if (item is Map) MacroMoveRow.fromJson(Map<String, dynamic>.from(item)),
      ],
    );
  }
}

class MacroBoard {
  const MacroBoard({
    this.regime = VolRegime.empty,
    this.sleeves = const [],
    this.note = '',
  });

  final VolRegime regime;
  final List<MacroSleeveBlock> sleeves;
  final String note;

  static const empty = MacroBoard();

  factory MacroBoard.fromJson(Map<String, dynamic> json) {
    return MacroBoard(
      regime: VolRegime.fromJson(
        json['regime'] is Map ? Map<String, dynamic>.from(json['regime'] as Map) : null,
      ),
      sleeves: [
        if (json['sleeves'] is List)
          for (final item in json['sleeves'])
            if (item is Map)
              MacroSleeveBlock.fromJson(Map<String, dynamic>.from(item)),
      ],
      note: '${json['note'] ?? ''}',
    );
  }
}

class EdgeInstrument {
  const EdgeInstrument({
    required this.symbol,
    this.ready = false,
    this.px,
    this.dayPct,
    this.dRsi14,
    this.wRsi14,
    this.vs50d,
    this.vs200d,
    this.slope200,
    this.regime,
    this.tags = const [],
  });

  final String symbol;
  final bool ready;
  final double? px;
  final double? dayPct;
  final double? dRsi14;
  final double? wRsi14;
  final double? vs50d;
  final double? vs200d;
  final String? slope200;
  final String? regime;
  final List<String> tags;

  factory EdgeInstrument.fromJson(Map<String, dynamic> json) {
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    final raw = json['tags'];
    return EdgeInstrument(
      symbol: (json['symbol'] as String? ?? '').toUpperCase(),
      ready: json['ready'] == true,
      px: n(json['px']),
      dayPct: n(json['day_pct']),
      dRsi14: n(json['d_rsi14']),
      wRsi14: n(json['w_rsi14']),
      vs50d: n(json['vs50d']),
      vs200d: n(json['vs200d']),
      slope200: json['slope200'] as String?,
      regime: json['regime'] as String?,
      tags: [
        if (raw is List)
          for (final t in raw)
            if (t != null && '$t'.isNotEmpty) '$t',
      ],
    );
  }
}

class EdgeSection {
  const EdgeSection({
    required this.id,
    required this.label,
    this.rows = const [],
  });

  final String id;
  final String label;
  final List<EdgeInstrument> rows;

  factory EdgeSection.fromJson(Map<String, dynamic> json) {
    final raw = json['rows'];
    return EdgeSection(
      id: '${json['id'] ?? ''}',
      label: '${json['label'] ?? ''}',
      rows: [
        if (raw is List)
          for (final item in raw)
            if (item is Map)
              EdgeInstrument.fromJson(Map<String, dynamic>.from(item)),
      ],
    );
  }
}

class EdgesBoard {
  const EdgesBoard({
    this.regime = VolRegime.empty,
    this.online = const [],
    this.sections = const [],
    this.setupBuckets = const {},
    this.note = '',
  });

  final VolRegime regime;
  final List<String> online;
  final List<EdgeSection> sections;
  final Map<String, List<String>> setupBuckets;
  final String note;

  static const empty = EdgesBoard();

  factory EdgesBoard.fromJson(Map<String, dynamic> json) {
    final buckets = <String, List<String>>{};
    final rawB = json['setup_buckets'];
    if (rawB is Map) {
      rawB.forEach((key, value) {
        if (value is List) {
          buckets['$key'] = [
            for (final s in value)
              if (s != null && '$s'.isNotEmpty) '$s'.toUpperCase(),
          ];
        }
      });
    }
    return EdgesBoard(
      regime: VolRegime.fromJson(
        json['regime'] is Map ? Map<String, dynamic>.from(json['regime'] as Map) : null,
      ),
      online: [
        if (json['online'] is List)
          for (final t in json['online'])
            if (t != null && '$t'.isNotEmpty) '$t',
      ],
      sections: [
        if (json['sections'] is List)
          for (final item in json['sections'])
            if (item is Map) EdgeSection.fromJson(Map<String, dynamic>.from(item)),
      ],
      setupBuckets: buckets,
      note: '${json['note'] ?? ''}',
    );
  }
}

class FractalRow {
  const FractalRow({
    required this.symbol,
    this.d65d,
    this.d130d,
    this.move65d,
    this.move130d,
    this.read = '',
    this.tags = const [],
  });

  final String symbol;
  final double? d65d;
  final double? d130d;
  final double? move65d;
  final double? move130d;
  final String read;
  final List<String> tags;

  bool get isFragile => read == 'FRAGILE' || tags.contains('FRAGILE');

  factory FractalRow.fromJson(Map<String, dynamic> json) {
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    return FractalRow(
      symbol: (json['symbol'] as String? ?? '').toUpperCase(),
      d65d: n(json['d_65d']),
      d130d: n(json['d_130d']),
      move65d: n(json['move_65d']),
      move130d: n(json['move_130d']),
      read: '${json['read'] ?? ''}',
      tags: [
        if (json['tags'] is List)
          for (final t in json['tags'])
            if (t != null && '$t'.isNotEmpty) '$t',
      ],
    );
  }
}

class FractalStatus {
  const FractalStatus({
    this.available = false,
    this.reason = '',
    this.source = '',
    this.expected = '',
    this.rows = const [],
    this.columns = const [],
  });

  final bool available;
  final String reason;
  final String source;
  final String expected;
  final List<FractalRow> rows;
  final List<String> columns;

  static const empty = FractalStatus(
    reason: 'Fractal: SPEC 25/27 — no rows yet',
    expected: 'whats-news fractal_scan (SPEC 25/27)',
  );

  factory FractalStatus.fromJson(Map<String, dynamic> json) {
    return FractalStatus(
      available: json['available'] == true,
      reason: '${json['reason'] ?? json['message'] ?? 'Fractal: SPEC 25/27'}',
      source: '${json['source'] ?? ''}',
      expected: '${json['expected'] ?? ''}',
      columns: [
        if (json['columns'] is List)
          for (final c in json['columns'])
            if (c != null) '$c',
      ],
      rows: [
        if (json['rows'] is List)
          for (final item in json['rows'])
            if (item is Map) FractalRow.fromJson(Map<String, dynamic>.from(item)),
      ],
    );
  }
}

class TapeRow {
  const TapeRow({
    required this.symbol,
    this.price,
    this.changePct,
    this.regime,
    this.ready = false,
    this.groupTag = '',
    this.isEp = false,
    this.isVolSurge = false,
    this.isNearHigh = false,
    this.breakoutScore,
    this.adrPct,
  });

  final String symbol;
  final double? price;
  final double? changePct;
  final String? regime;
  final bool ready;
  final String groupTag;
  final bool isEp;
  final bool isVolSurge;
  final bool isNearHigh;
  final double? breakoutScore;
  final double? adrPct;

  factory TapeRow.fromJson(Map<String, dynamic> json) {
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    return TapeRow(
      symbol: (json['symbol'] as String? ?? '').toUpperCase(),
      price: n(json['price']),
      changePct: n(json['change_pct']),
      regime: json['regime'] as String?,
      ready: json['ready'] == true,
      groupTag: '${json['group_tag'] ?? ''}',
      isEp: json['is_ep'] == true,
      isVolSurge: json['is_vol_surge'] == true,
      isNearHigh: json['is_near_high'] == true,
      breakoutScore: n(json['breakout_score']),
      adrPct: n(json['adr_pct']),
    );
  }
}

class GroupRollup {
  const GroupRollup({
    required this.group,
    required this.n,
    this.avgChangePct,
  });

  final String group;
  final int n;
  final double? avgChangePct;

  factory GroupRollup.fromJson(Map<String, dynamic> json) {
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    return GroupRollup(
      group: '${json['group'] ?? 'Ungrouped'}',
      n: json['n'] is num ? (json['n'] as num).toInt() : 0,
      avgChangePct: n(json['avg_change_pct']),
    );
  }
}

class PortfolioSnapshot {
  const PortfolioSnapshot({
    this.count = 0,
    this.readyCount = 0,
    this.symbols = const [],
    this.breakoutQueue = const [],
    this.heatmap = const [],
    this.groupRollup = const [],
    this.message,
  });

  final int count;
  final int readyCount;
  final List<TapeRow> symbols;
  final List<TapeRow> breakoutQueue;
  final List<TapeRow> heatmap;
  final List<GroupRollup> groupRollup;
  final String? message;

  static const empty = PortfolioSnapshot();

  TapeRow? named(String symbol) {
    final key = symbol.toUpperCase();
    for (final s in symbols) {
      if (s.symbol == key) return s;
    }
    return null;
  }

  /// Desk heuristic from real snapshot fields — not a forecast.
  String get tapeTemperature {
    if (readyCount == 0) return 'cold';
    final up = heatmap.where((r) => r.regime == 'uptrend').length;
    final down = heatmap.where((r) => r.regime == 'downtrend').length;
    final bq = breakoutQueue.length;
    if (bq >= 3 || (up > down && bq >= 1)) return 'hot';
    if (bq >= 1 || up >= down) return 'warm';
    return 'cool';
  }

  factory PortfolioSnapshot.fromJson(Map<String, dynamic> json) {
    List<TapeRow> rows(Object? raw) {
      if (raw is! List) return const [];
      return [
        for (final item in raw)
          if (item is Map) TapeRow.fromJson(Map<String, dynamic>.from(item)),
      ];
    }

    return PortfolioSnapshot(
      count: json['count'] is num ? (json['count'] as num).toInt() : 0,
      readyCount: json['ready_count'] is num ? (json['ready_count'] as num).toInt() : 0,
      symbols: rows(json['symbols']),
      breakoutQueue: rows(json['breakout_queue']),
      heatmap: rows(json['heatmap']),
      groupRollup: [
        if (json['group_rollup'] is List)
          for (final item in json['group_rollup'])
            if (item is Map) GroupRollup.fromJson(Map<String, dynamic>.from(item)),
      ],
      message: json['message'] as String?,
    );
  }
}

class DeskNote {
  const DeskNote({
    required this.symbol,
    this.ready = false,
    this.regime,
    this.adrPct,
    this.dist20dHighPct,
    this.volRatio,
    this.isEp = false,
    this.isVolSurge = false,
    this.isNearHigh = false,
    this.breakoutScore,
    this.changePct,
    this.error,
  });

  final String symbol;
  final bool ready;
  final String? regime;
  final double? adrPct;
  final double? dist20dHighPct;
  final double? volRatio;
  final bool isEp;
  final bool isVolSurge;
  final bool isNearHigh;
  final double? breakoutScore;
  final double? changePct;
  final String? error;

  static const empty = DeskNote(symbol: '');

  factory DeskNote.fromJson(Map<String, dynamic> json) {
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    return DeskNote(
      symbol: (json['symbol'] as String? ?? '').toUpperCase(),
      ready: json['ready'] == true,
      regime: json['regime'] as String?,
      adrPct: n(json['adr_pct']),
      dist20dHighPct: n(json['dist_20d_high_pct']),
      volRatio: n(json['vol_ratio_5_20']),
      isEp: json['is_ep'] == true,
      isVolSurge: json['is_vol_surge'] == true,
      isNearHigh: json['is_near_high'] == true,
      breakoutScore: n(json['breakout_score']),
      changePct: n(json['change_pct']),
      error: json['error'] as String?,
    );
  }
}

class SpyRs {
  const SpyRs({this.ready = false, this.lastRatio, this.note = ''});

  final bool ready;
  final double? lastRatio;
  final String note;

  static const empty = SpyRs();

  factory SpyRs.fromJson(Map<String, dynamic> json) {
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    return SpyRs(
      ready: json['ready'] == true,
      lastRatio: n(json['last_ratio']),
      note: '${json['note'] ?? ''}',
    );
  }
}

class BookPosition {
  const BookPosition({
    required this.symbol,
    this.id,
    this.qty,
    this.side = 'long',
    this.avgCost,
    this.price,
    this.marketValue,
    this.dayPnl,
    this.unrealized,
    this.dayPct,
    this.ready = false,
  });

  final int? id;
  final String symbol;
  final double? qty;
  final String side;
  final double? avgCost;
  final double? price;
  final double? marketValue;
  final double? dayPnl;
  final double? unrealized;
  final double? dayPct;
  final bool ready;

  factory BookPosition.fromJson(Map<String, dynamic> json) {
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    return BookPosition(
      id: json['id'] is num ? (json['id'] as num).toInt() : int.tryParse('${json['id']}'),
      symbol: (json['symbol'] as String? ?? '').toUpperCase(),
      qty: n(json['qty']),
      side: '${json['side'] ?? 'long'}',
      avgCost: n(json['avg_cost']),
      price: n(json['price']),
      marketValue: n(json['market_value']),
      dayPnl: n(json['day_pnl']),
      unrealized: n(json['unrealized']),
      dayPct: n(json['day_pct']),
      ready: json['ready'] == true,
    );
  }
}

class BookPnl {
  const BookPnl({
    this.ready = false,
    this.deskName = 'Whats-News',
    this.note = '',
    this.message = '',
    this.todayPnl,
    this.todayPnlPct,
    this.nav,
    this.gross = 0,
    this.longMv = 0,
    this.shortMv = 0,
    this.net = 0,
    this.betaSpy,
    this.varNote = '',
    this.hist95Pct,
    this.param95Pct,
    this.es95Pct,
    this.distMean,
    this.distStdev,
    this.distN = 0,
    this.curve = const [],
    this.curveLabel = '',
    this.positions = const [],
    this.tape = const [],
  });

  final bool ready;
  final String deskName;
  final String note;
  final String message;
  final double? todayPnl;
  final double? todayPnlPct;
  final double? nav;
  final double gross;
  final double longMv;
  final double shortMv;
  final double net;
  final double? betaSpy;
  final String varNote;
  final double? hist95Pct;
  final double? param95Pct;
  final double? es95Pct;
  final double? distMean;
  final double? distStdev;
  final int distN;
  final List<(String, double)> curve;
  final String curveLabel;
  final List<BookPosition> positions;
  final List<BookPosition> tape;

  static const empty = BookPnl(
    message: 'Empty paper book. Import a Fidelity CSV or add a line.',
    note: 'Paper / local only. No invented P&L.',
  );

  factory BookPnl.fromJson(Map<String, dynamic> json) {
    double? n(Object? v) {
      if (v is num) return v.toDouble();
      return double.tryParse('$v');
    }

    final exp = json['exposure'] is Map ? Map<String, dynamic>.from(json['exposure'] as Map) : const <String, dynamic>{};
    final vr = json['var'] is Map ? Map<String, dynamic>.from(json['var'] as Map) : const <String, dynamic>{};
    final dist = json['distribution'] is Map ? Map<String, dynamic>.from(json['distribution'] as Map) : const <String, dynamic>{};
    Map<String, dynamic> pack(Object? raw) => raw is Map ? Map<String, dynamic>.from(raw) : const {};

    return BookPnl(
      ready: json['ready'] == true,
      deskName: '${json['desk_name'] ?? 'Whats-News'}',
      note: '${json['note'] ?? ''}',
      message: '${json['message'] ?? ''}',
      todayPnl: n(json['today_pnl']),
      todayPnlPct: n(json['today_pnl_pct']),
      nav: n(json['nav']),
      gross: n(exp['gross']) ?? 0,
      longMv: n(exp['long']) ?? 0,
      shortMv: n(exp['short']) ?? 0,
      net: n(exp['net']) ?? 0,
      betaSpy: n(json['beta_spy']),
      varNote: '${vr['note'] ?? ''}',
      hist95Pct: n(pack(vr['hist_95'])['pct']),
      param95Pct: n(pack(vr['param_95'])['pct']),
      es95Pct: n(pack(vr['es_95'])['pct']),
      distMean: n(dist['mean']),
      distStdev: n(dist['stdev']),
      distN: n(dist['n'])?.toInt() ?? 0,
      curve: [
        if (json['equity_curve'] is List)
          for (final p in json['equity_curve'])
            if (p is Map && n(p['nav']) != null) ('${p['date'] ?? ''}', n(p['nav'])!),
      ],
      curveLabel: '${json['curve_label'] ?? ''}',
      positions: [
        if (json['positions'] is List)
          for (final p in json['positions'])
            if (p is Map) BookPosition.fromJson(Map<String, dynamic>.from(p)),
      ],
      tape: [
        if (json['tape'] is List)
          for (final p in json['tape'])
            if (p is Map) BookPosition.fromJson(Map<String, dynamic>.from(p)),
      ],
    );
  }
}
