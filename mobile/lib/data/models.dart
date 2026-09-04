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
  });

  final String symbol;
  final String name;
  final String sector;
  final String groupTag;

  bool get isUniverseArchive => groupTag.startsWith('univ:');

  factory WatchSymbol.fromJson(Map<String, dynamic> json) {
    return WatchSymbol(
      symbol: (json['symbol'] as String? ?? '').toUpperCase(),
      name: json['name'] as String? ?? '',
      sector: json['sector'] as String? ?? '',
      groupTag: json['group_tag'] as String? ?? '',
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
  final String? error;

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
      error: json['error'] as String?,
    );
  }
}
