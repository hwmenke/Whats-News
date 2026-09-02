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
