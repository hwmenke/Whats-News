/// HTTP client for the Whats-News Python data layer.
///
/// Talks to the same Flask JSON the Dash app uses (`./start.sh` on :8050,
/// or `python -m data_service.app` on :8051). No API keys. Paper/local only.
library;

import 'dart:convert';

import 'package:http/http.dart' as http;

import 'models.dart';

const kDefaultApiBase = String.fromEnvironment(
  'WHATS_NEWS_API',
  defaultValue: 'http://127.0.0.1:8050',
);

class WhatsNewsApi {
  WhatsNewsApi({
    String? baseUrl,
    http.Client? httpClient,
  })  : _client = httpClient ?? http.Client(),
        baseUrl = _normalize(baseUrl ?? kDefaultApiBase);

  final http.Client _client;
  String baseUrl;

  static String _normalize(String url) {
    var out = url.trim();
    if (out.endsWith('/')) {
      out = out.substring(0, out.length - 1);
    }
    return out;
  }

  void setBaseUrl(String url) {
    baseUrl = _normalize(url);
  }

  Uri _uri(String path, [Map<String, String>? query]) {
    return Uri.parse('$baseUrl$path').replace(queryParameters: query);
  }

  Future<dynamic> _get(String path, [Map<String, String>? query]) async {
    final res = await _client.get(
      _uri(path, query),
      headers: const {'Accept': 'application/json'},
    );
    return _decode(res);
  }

  Future<dynamic> _send(
    String method,
    String path, {
    Object? body,
  }) async {
    final uri = _uri(path);
    final headers = {
      'Accept': 'application/json',
      if (body != null) 'Content-Type': 'application/json',
    };
    final encoded = body == null ? null : jsonEncode(body);
    late http.Response res;
    if (method == 'POST') {
      res = await _client.post(uri, headers: headers, body: encoded);
    } else if (method == 'DELETE') {
      res = await _client.delete(uri, headers: headers, body: encoded);
    } else {
      throw ApiException('Unsupported method $method');
    }
    return _decode(res);
  }

  dynamic _decode(http.Response res) {
    dynamic payload;
    if (res.body.isNotEmpty) {
      try {
        payload = jsonDecode(res.body);
      } catch (_) {
        payload = res.body;
      }
    }
    if (res.statusCode >= 400) {
      String message = 'HTTP ${res.statusCode}';
      String? code;
      int? retry;
      if (payload is Map) {
        message = '${payload['error'] ?? payload['message'] ?? message}';
        code = payload['code'] as String?;
        retry = payload['retry_after_sec'] is num
            ? (payload['retry_after_sec'] as num).toInt()
            : null;
      }
      throw ApiException(
        message,
        status: res.statusCode,
        code: code,
        retryAfterSec: retry,
      );
    }
    return payload;
  }

  Future<Map<String, dynamic>> health() async {
    final raw = await _get('/api/health');
    if (raw is Map<String, dynamic>) return raw;
    if (raw is Map) return Map<String, dynamic>.from(raw);
    return {'ok': false, 'error': 'unexpected health payload'};
  }

  Future<List<WatchSymbol>> listSymbols({bool desk = true}) async {
    final raw = await _get(
      '/api/symbols',
      desk ? const {'desk': '1'} : null,
    );
    if (raw is! List) return const [];
    return [
      for (final item in raw)
        if (item is Map)
          WatchSymbol.fromJson(Map<String, dynamic>.from(item)),
    ];
  }

  Future<void> addSymbol(String symbol) async {
    final sym = symbol.trim().toUpperCase();
    if (sym.isEmpty) {
      throw ApiException('symbol is required');
    }
    await _send('POST', '/api/symbols', body: {'symbol': sym});
  }

  Future<void> removeSymbol(String symbol) async {
    await _send('DELETE', '/api/symbols/${symbol.trim().toUpperCase()}');
  }

  Future<Map<String, dynamic>> fetchSymbol(String symbol) async {
    final raw = await _send(
      'POST',
      '/api/fetch/${symbol.trim().toUpperCase()}',
    );
    if (raw is Map<String, dynamic>) return raw;
    if (raw is Map) return Map<String, dynamic>.from(raw);
    return {};
  }

  Future<List<OhlcvBar>> getOhlcv(
    String symbol, {
    String freq = 'daily',
    int limit = 180,
  }) async {
    final raw = await _get('/api/ohlcv/${symbol.trim().toUpperCase()}', {
      'freq': freq,
      'limit': '$limit',
    });
    if (raw is! List) return const [];
    return [
      for (final item in raw)
        if (item is Map) OhlcvBar.fromJson(Map<String, dynamic>.from(item)),
    ];
  }

  Future<NewsFeed> getNews({String? symbol}) async {
    final path = (symbol == null || symbol.trim().isEmpty)
        ? '/api/news'
        : '/api/news/${symbol.trim().toUpperCase()}';
    final raw = await _get(path);
    if (raw is Map<String, dynamic>) return NewsFeed.fromJson(raw);
    if (raw is Map) return NewsFeed.fromJson(Map<String, dynamic>.from(raw));
    return const NewsFeed(articles: []);
  }
}
