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

  Future<MarketMovesBoard> getMarketMoves() async {
    final raw = await _get('/api/market-moves');
    if (raw is Map<String, dynamic>) return MarketMovesBoard.fromJson(raw);
    if (raw is Map) return MarketMovesBoard.fromJson(Map<String, dynamic>.from(raw));
    return MarketMovesBoard.empty;
  }

  /// Column + measure registry for Market Moves + ENGINE.
  /// Flutter Customize path: persist `boardColumns` on `whats-news-desk-prefs`.
  Future<BoardRegistryCatalog> getBoardRegistry() async {
    final raw = await _get('/api/boards/registry');
    if (raw is Map<String, dynamic>) return BoardRegistryCatalog.fromJson(raw);
    if (raw is Map) return BoardRegistryCatalog.fromJson(Map<String, dynamic>.from(raw));
    return BoardRegistryCatalog.empty;
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

  /// Seed MM core (+ optional Core 50) then Fetch Yahoo for desk names missing ≥20 bars.
  /// Documented: docs/YAHOO_SEED.md. Does not invent prices.
  Future<Map<String, dynamic>> seedFetchDesk({bool core50 = true, double delay = 0.4}) async {
    final raw = await _send(
      'POST',
      '/api/desk/seed-fetch',
      body: {'core50': core50 ? '1' : '0', 'delay': delay, 'period': '1y'},
    );
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

  Future<FinvizScreener> getFinvizScreener({String preset = 'qulla_momentum', bool force = false}) async {
    try {
      final raw = force
          ? await _send('POST', '/api/finviz/screener/refresh', body: {'preset': preset})
          : await _get('/api/finviz/screener', {'preset': preset});
      if (raw is Map<String, dynamic>) return FinvizScreener.fromJson(raw);
      if (raw is Map) return FinvizScreener.fromJson(Map<String, dynamic>.from(raw));
    } on ApiException {
      return FinvizScreener.empty;
    }
    return FinvizScreener.empty;
  }

  Future<FinvizQuote> getFinvizQuote(String symbol, {bool force = false}) async {
    try {
      final raw = await _get(
        '/api/finviz/quote/${symbol.trim().toUpperCase()}',
        force ? const {'force': '1'} : null,
      );
      if (raw is Map<String, dynamic>) return FinvizQuote.fromJson(raw);
      if (raw is Map) return FinvizQuote.fromJson(Map<String, dynamic>.from(raw));
    } on ApiException {
      return FinvizQuote.empty;
    }
    return FinvizQuote.empty;
  }

  Future<Map<String, dynamic>> getFinvizSettings() async {
    try {
      final raw = await _get('/api/finviz/settings');
      if (raw is Map<String, dynamic>) return raw;
      if (raw is Map) return Map<String, dynamic>.from(raw);
    } on ApiException {
      return const {};
    }
    return const {};
  }

  Future<Map<String, dynamic>> setFinvizSettings({bool? enabled, int? ttlSec}) async {
    final raw = await _send('PUT', '/api/finviz/settings', body: {
      if (enabled != null) 'enabled': enabled,
      if (ttlSec != null) 'ttl_sec': ttlSec,
    });
    if (raw is Map<String, dynamic>) return raw;
    if (raw is Map) return Map<String, dynamic>.from(raw);
    return const {};
  }

  Future<HmmRegime> getHmmRegime({String symbol = 'SPY', int states = 2}) async {
    try {
      final raw = await _get('/api/hmm/regime', {
        'symbol': symbol,
        'states': '$states',
      });
      if (raw is Map<String, dynamic>) return HmmRegime.fromJson(raw);
      if (raw is Map) return HmmRegime.fromJson(Map<String, dynamic>.from(raw));
    } on ApiException {
      return HmmRegime.empty;
    }
    return HmmRegime.empty;
  }

  Future<HmmRegime> getHmmScan({int states = 2, String? state, String view = 'all'}) async {
    try {
      final raw = await _get('/api/hmm/scan', {
        'desk': '1',
        'states': '$states',
        'view': view,
        if (state != null && state.isNotEmpty) 'state': state,
      });
      if (raw is Map<String, dynamic>) return HmmRegime.fromJson(raw);
      if (raw is Map) return HmmRegime.fromJson(Map<String, dynamic>.from(raw));
    } on ApiException {
      return HmmRegime.empty;
    }
    return HmmRegime.empty;
  }

  Future<ComboScan> getHmmCombo({int states = 2, String? state}) async {
    try {
      final raw = await _get('/api/hmm/combo', {
        'desk': '1',
        'states': '$states',
        if (state != null && state.isNotEmpty) 'state': state,
      });
      if (raw is Map<String, dynamic>) return ComboScan.fromJson(raw);
      if (raw is Map) return ComboScan.fromJson(Map<String, dynamic>.from(raw));
    } on ApiException {
      return ComboScan.empty;
    }
    return ComboScan.empty;
  }

  Future<ScanPack> getScanPack({String lens = 'all'}) async {
    try {
      final raw = await _get('/api/scans/pack', {'desk': '1', 'lens': lens});
      if (raw is Map<String, dynamic>) return ScanPack.fromJson(raw);
      if (raw is Map) return ScanPack.fromJson(Map<String, dynamic>.from(raw));
    } on ApiException {
      return ScanPack.empty;
    }
    return ScanPack.empty;
  }

  Future<Map<String, dynamic>> _engineGet(String path, [Map<String, String>? q]) async {
    try {
      final raw = await _get(path, {'desk': '1', ...?q});
      if (raw is Map<String, dynamic>) return raw;
      if (raw is Map) return Map<String, dynamic>.from(raw);
    } on ApiException {
      return const {};
    }
    return const {};
  }

  Future<EngineBoard> getEngineCommand() async {
    final raw = await _engineGet('/api/engine/command');
    return raw.isEmpty ? EngineBoard.empty : EngineBoard.fromJson(raw);
  }

  Future<EngineBoard> getEngineBoard() async {
    final raw = await _engineGet('/api/engine/board');
    return raw.isEmpty ? EngineBoard.empty : EngineBoard.fromJson(raw);
  }

  Future<RsiCounterBoard> getRsiCounter({int n = 14, int lag = 5}) async {
    final raw = await _engineGet('/api/engine/rsi-counter', {'n': '$n', 'lag': '$lag'});
    return raw.isEmpty ? RsiCounterBoard.empty : RsiCounterBoard.fromJson(raw);
  }

  Future<PatternBoard> getEnginePatterns() async {
    final raw = await _engineGet('/api/engine/patterns');
    return raw.isEmpty ? PatternBoard.empty : PatternBoard.fromJson(raw);
  }

  Future<StretchBoard> getEngineStretch() async {
    final raw = await _engineGet('/api/engine/stretch');
    return raw.isEmpty ? StretchBoard.empty : StretchBoard.fromJson(raw);
  }

  Future<SigmaBoard> getEngineSigma() async {
    final raw = await _engineGet('/api/engine/sigma');
    return raw.isEmpty ? SigmaBoard.empty : SigmaBoard.fromJson(raw);
  }

  Future<EngineMaps> getEngineMaps() async {
    final raw = await _engineGet('/api/engine/maps');
    return raw.isEmpty ? EngineMaps.empty : EngineMaps.fromJson(raw);
  }

  Future<WarningsBoard> getEngineWarnings() async {
    final raw = await _engineGet('/api/engine/warnings');
    return raw.isEmpty ? WarningsBoard.empty : WarningsBoard.fromJson(raw);
  }

  Future<ScanBreadth> getScanBreadth() async {
    try {
      final raw = await _get('/api/scans/breadth', const {'desk': '1'});
      if (raw is Map<String, dynamic>) return ScanBreadth.fromJson(raw);
      if (raw is Map) return ScanBreadth.fromJson(Map<String, dynamic>.from(raw));
    } on ApiException {
      return ScanBreadth.empty;
    }
    return ScanBreadth.empty;
  }

  Future<Map<String, dynamic>> getAlpacaStatus() async {
    try {
      final raw = await _get('/api/alpaca/status');
      if (raw is Map<String, dynamic>) return raw;
      if (raw is Map) return Map<String, dynamic>.from(raw);
    } on ApiException {
      return const {};
    }
    return const {};
  }

  Future<Map<String, dynamic>> syncAlpacaPaper() async {
    final raw = await _send('POST', '/api/alpaca/sync');
    if (raw is Map<String, dynamic>) return raw;
    if (raw is Map) return Map<String, dynamic>.from(raw);
    return const {};
  }

  Future<BookPnl> getBookPnl() async {
    try {
      final raw = await _get('/api/book/pnl');
      if (raw is Map<String, dynamic>) return BookPnl.fromJson(raw);
      if (raw is Map) return BookPnl.fromJson(Map<String, dynamic>.from(raw));
    } on ApiException {
      return BookPnl.empty;
    }
    return BookPnl.empty;
  }

  Future<BookPosition> addBookPosition({
    required String symbol,
    required double qty,
    String side = 'long',
    double? avgCost,
  }) async {
    final raw = await _send('POST', '/api/book/positions', body: {
      'symbol': symbol,
      'qty': qty,
      'side': side,
      if (avgCost != null) 'avg_cost': avgCost,
    });
    if (raw is Map<String, dynamic>) return BookPosition.fromJson(raw);
    if (raw is Map) return BookPosition.fromJson(Map<String, dynamic>.from(raw));
    return BookPosition(symbol: symbol.toUpperCase(), qty: qty, side: side);
  }

  Future<void> deleteBookPosition(int id) async {
    await _send('DELETE', '/api/book/positions/$id');
  }

  Future<Map<String, dynamic>> importBookCsv(String csv, {bool replace = false}) async {
    final raw = await _send('POST', '/api/book/import', body: {
      'csv': csv,
      'replace': replace,
    });
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
