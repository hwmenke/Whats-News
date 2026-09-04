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
    } else if (method == 'PUT') {
      res = await _client.put(uri, headers: headers, body: encoded);
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

  Future<void> setSymbolGroup(String symbol, String groupTag) async {
    await _send(
      'PUT',
      '/api/symbols/${symbol.trim().toUpperCase()}/group',
      body: {'group_tag': groupTag},
    );
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

  Future<IndicatorPack> getIndicators(
    String symbol, {
    String freq = 'daily',
  }) async {
    final raw = await _get('/api/indicators/${symbol.trim().toUpperCase()}', {
      'freq': freq,
    });
    if (raw is Map<String, dynamic>) return IndicatorPack.fromJson(raw);
    if (raw is Map) {
      return IndicatorPack.fromJson(Map<String, dynamic>.from(raw));
    }
    return IndicatorPack.empty;
  }

  Future<List<TrendScanRow>> getTrendScan({
    bool desk = true,
    String freq = 'daily',
  }) async {
    final raw = await _get('/api/trend-scan', {
      if (desk) 'desk': '1',
      'freq': freq,
    });
    if (raw is! List) return const [];
    return [
      for (final item in raw)
        if (item is Map)
          TrendScanRow.fromJson(Map<String, dynamic>.from(item)),
    ];
  }

  Future<List<ScannerRow>> getScanner({bool universe = false}) async {
    final raw = await _get('/api/scanner', {
      'universe': universe ? '1' : '0',
    });
    if (raw is! List) return const [];
    return [
      for (final item in raw)
        if (item is Map) ScannerRow.fromJson(Map<String, dynamic>.from(item)),
    ];
  }

  Future<List<SetupScanRow>> getSetupScan({bool universe = false}) async {
    final raw = await _get('/api/setups/scan', {
      'universe': universe ? '1' : '0',
    });
    List<dynamic> rows = const [];
    if (raw is Map && raw['results'] is List) {
      rows = raw['results'] as List;
    } else if (raw is List) {
      rows = raw;
    }
    return [
      for (final item in rows)
        if (item is Map) SetupScanRow.fromJson(Map<String, dynamic>.from(item)),
    ];
  }

  Future<Map<String, dynamic>> getScannerStatus() async {
    final raw = await _get('/api/scanner/status');
    if (raw is Map<String, dynamic>) return raw;
    if (raw is Map) return Map<String, dynamic>.from(raw);
    return const {};
  }

  Future<PortfolioSnapshot> getPortfolioSnapshot() async {
    final raw = await _get('/api/portfolio/snapshot');
    if (raw is Map<String, dynamic>) return PortfolioSnapshot.fromJson(raw);
    if (raw is Map) {
      return PortfolioSnapshot.fromJson(Map<String, dynamic>.from(raw));
    }
    return PortfolioSnapshot.empty;
  }

  Future<DeskNote> getPmDesk(String symbol) async {
    try {
      final raw = await _get('/api/pm-desk/${symbol.trim().toUpperCase()}');
      if (raw is Map<String, dynamic>) return DeskNote.fromJson(raw);
      if (raw is Map) return DeskNote.fromJson(Map<String, dynamic>.from(raw));
    } on ApiException catch (e) {
      if (e.status == 404) {
        return DeskNote(symbol: symbol.toUpperCase(), ready: false, error: e.message);
      }
      rethrow;
    }
    return DeskNote(symbol: symbol.toUpperCase(), ready: false);
  }

  Future<SpyRs> getSpyRs(String symbol) async {
    try {
      final raw = await _get('/api/spy-rs/${symbol.trim().toUpperCase()}');
      if (raw is Map<String, dynamic>) return SpyRs.fromJson(raw);
      if (raw is Map) return SpyRs.fromJson(Map<String, dynamic>.from(raw));
    } on ApiException {
      return SpyRs.empty;
    }
    return SpyRs.empty;
  }

  Future<List<Sleeve>> getSleeves() async {
    final raw = await _get('/api/sleeves');
    List<dynamic> rows = const [];
    if (raw is Map && raw['sleeves'] is List) {
      rows = raw['sleeves'] as List;
    }
    return [
      for (final item in rows)
        if (item is Map) Sleeve.fromJson(Map<String, dynamic>.from(item)),
    ];
  }

  Future<Map<String, dynamic>> seedSleeve(String id) async {
    final raw = await _send('POST', '/api/sleeves/${id.trim()}/seed');
    if (raw is Map<String, dynamic>) return raw;
    if (raw is Map) return Map<String, dynamic>.from(raw);
    return const {};
  }

  Future<MacroBoard> getMacroBoard() async {
    final raw = await _get('/api/macro/board');
    if (raw is Map<String, dynamic>) return MacroBoard.fromJson(raw);
    if (raw is Map) return MacroBoard.fromJson(Map<String, dynamic>.from(raw));
    return MacroBoard.empty;
  }

  Future<EdgesBoard> getEdgesBoard() async {
    final raw = await _get('/api/edges/board');
    if (raw is Map<String, dynamic>) return EdgesBoard.fromJson(raw);
    if (raw is Map) return EdgesBoard.fromJson(Map<String, dynamic>.from(raw));
    return EdgesBoard.empty;
  }

  Future<FractalStatus> getFractalStatus() async {
    try {
      final raw = await _get('/api/fractal/status');
      if (raw is Map<String, dynamic>) return FractalStatus.fromJson(raw);
      if (raw is Map) return FractalStatus.fromJson(Map<String, dynamic>.from(raw));
    } on ApiException {
      return FractalStatus.empty;
    }
    return FractalStatus.empty;
  }

  Future<FractalStatus> getFractalScan() async {
    try {
      final raw = await _get('/api/fractal/scan', const {'desk': '1'});
      if (raw is Map<String, dynamic>) return FractalStatus.fromJson(raw);
      if (raw is Map) return FractalStatus.fromJson(Map<String, dynamic>.from(raw));
    } on ApiException {
      return FractalStatus.empty;
    }
    return FractalStatus.empty;
  }

  Future<Map<String, dynamic>> seedCore50() async {
    final raw = await _send('POST', '/api/universe/core50');
    if (raw is Map<String, dynamic>) return raw;
    if (raw is Map) return Map<String, dynamic>.from(raw);
    return const {};
  }

  Future<Map<String, dynamic>> universeSync({List<String> indices = const ['sp500']}) async {
    final raw = await _send(
      'POST',
      '/api/universe/sync',
      body: {'indices': indices},
    );
    if (raw is Map<String, dynamic>) return raw;
    if (raw is Map) return Map<String, dynamic>.from(raw);
    return const {};
  }

  Future<NewsFeed> getNews({String? symbol, bool desk = false}) async {
    if (symbol != null && symbol.trim().isNotEmpty) {
      final raw = await _get('/api/news/${symbol.trim().toUpperCase()}');
      if (raw is Map<String, dynamic>) return NewsFeed.fromJson(raw);
      if (raw is Map) return NewsFeed.fromJson(Map<String, dynamic>.from(raw));
      return const NewsFeed(articles: []);
    }
    final raw = await _get('/api/news', desk ? const {'desk': '1'} : null);
    if (raw is Map<String, dynamic>) return NewsFeed.fromJson(raw);
    if (raw is Map) return NewsFeed.fromJson(Map<String, dynamic>.from(raw));
    return const NewsFeed(articles: []);
  }
}
