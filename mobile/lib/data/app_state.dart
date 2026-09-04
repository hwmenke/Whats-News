import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import 'models.dart';

const kApiBasePref = 'whats-news-api-base';

/// App-wide state. UIKit-free; Android / Mac screens can bind to this later.
class WhatsNewsState extends ChangeNotifier {
  WhatsNewsState({WhatsNewsApi? api}) : api = api ?? WhatsNewsApi();

  final WhatsNewsApi api;

  List<WatchSymbol> symbols = const [];
  String? selectedSymbol;
  String freq = 'daily';
  List<OhlcvBar> bars = const [];
  IndicatorPack indicators = IndicatorPack.empty;
  NewsFeed news = const NewsFeed(articles: []);

  List<TrendScanRow> trendScan = const [];
  List<ScannerRow> metricScan = const [];
  List<SetupScanRow> setupScan = const [];
  String scanMode = 'trend';
  Map<String, dynamic> scannerStatus = const {};

  bool showKama10 = false;
  bool showKama20 = true;
  bool showKama50 = false;
  bool showBollinger = false;

  OhlcvBar? scrubBar;

  bool loadingWatchlist = false;
  bool loadingChart = false;
  bool loadingNews = false;
  bool loadingScans = false;
  bool fetching = false;
  String? error;
  String? chartError;
  String? scanError;
  String? throttleMessage;
  bool paperBanner = true;

  String get baseUrl => api.baseUrl;

  WatchSymbol? get selected {
    final sym = selectedSymbol;
    if (sym == null) return null;
    for (final s in symbols) {
      if (s.symbol == sym) return s;
    }
    return null;
  }

  OhlcvBar? get lastBar => bars.isEmpty ? null : bars.last;

  OhlcvBar? get displayBar => scrubBar ?? lastBar;

  double? get sessionChangePct {
    final bar = displayBar;
    if (bar == null || bars.length < 2) return null;
    final idx = bars.indexWhere((b) => b.date == bar.date);
    if (idx < 1) return null;
    final prev = bars[idx - 1].close;
    if (prev == 0) return null;
    return (bar.close - prev) / prev * 100;
  }

  Future<void> loadSavedBaseUrl() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(kApiBasePref);
    if (saved != null && saved.trim().isNotEmpty) {
      api.setBaseUrl(saved);
      notifyListeners();
    }
  }

  Future<void> setBaseUrl(String url) async {
    api.setBaseUrl(url);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(kApiBasePref, api.baseUrl);
    notifyListeners();
  }

  Future<void> refreshAll() async {
    await Future.wait([
      loadWatchlist(),
      loadNews(),
    ]);
    if (selectedSymbol != null) {
      await loadChart(selectedSymbol!);
    }
  }

  Future<void> loadWatchlist() async {
    loadingWatchlist = true;
    error = null;
    notifyListeners();
    try {
      symbols = await api.listSymbols(desk: true);
      if (selectedSymbol == null && symbols.isNotEmpty) {
        selectedSymbol = symbols.first.symbol;
      }
      if (selectedSymbol != null &&
          symbols.every((s) => s.symbol != selectedSymbol)) {
        selectedSymbol = symbols.isEmpty ? null : symbols.first.symbol;
      }
    } on ApiException catch (e) {
      error = _friendly(e);
    } catch (e) {
      error = 'Cannot reach $baseUrl. Start the Python app with ./start.sh';
    } finally {
      loadingWatchlist = false;
      notifyListeners();
    }
  }

  Future<void> selectSymbol(String symbol) async {
    selectedSymbol = symbol.toUpperCase();
    scrubBar = null;
    bars = const [];
    indicators = IndicatorPack.empty;
    chartError = null;
    notifyListeners();
    await Future.wait([
      loadChart(selectedSymbol!),
      loadNews(symbol: selectedSymbol),
    ]);
  }

  Future<void> setFreq(String next) async {
    if (next != 'daily' && next != 'weekly' && next != 'monthly') return;
    freq = next;
    scrubBar = null;
    notifyListeners();
    if (selectedSymbol != null) {
      await loadChart(selectedSymbol!);
    }
  }

  void setScrubBar(OhlcvBar? bar) {
    if (identical(scrubBar, bar)) return;
    scrubBar = bar;
    notifyListeners();
  }

  void toggleOverlay(String id) {
    switch (id) {
      case 'kama10':
        showKama10 = !showKama10;
      case 'kama20':
        showKama20 = !showKama20;
      case 'kama50':
        showKama50 = !showKama50;
      case 'bb':
        showBollinger = !showBollinger;
    }
    notifyListeners();
  }

  Future<void> addSymbol(String raw) async {
    final sym = raw.trim().toUpperCase();
    if (sym.isEmpty) return;
    error = null;
    notifyListeners();
    try {
      await api.addSymbol(sym);
      await loadWatchlist();
      await selectSymbol(sym);
      await fetchFromYahoo(sym);
    } on ApiException catch (e) {
      error = _friendly(e);
      notifyListeners();
    }
  }

  Future<void> removeSymbol(String symbol) async {
    try {
      await api.removeSymbol(symbol);
      if (selectedSymbol == symbol) {
        selectedSymbol = null;
        bars = const [];
        indicators = IndicatorPack.empty;
        scrubBar = null;
      }
      await loadWatchlist();
    } on ApiException catch (e) {
      error = _friendly(e);
      notifyListeners();
    }
  }

  Future<void> loadChart(String symbol) async {
    loadingChart = true;
    chartError = null;
    error = null;
    scrubBar = null;
    notifyListeners();
    try {
      bars = await api.getOhlcv(symbol, freq: freq, limit: 260);
      throttleMessage = null;
      try {
        indicators = await api.getIndicators(symbol, freq: freq);
      } on ApiException {
        indicators = IndicatorPack.empty;
      }
    } on ApiException catch (e) {
      bars = const [];
      indicators = IndicatorPack.empty;
      if (e.isMissingBars) {
        chartError = 'No stored $freq bars for $symbol. Fetch from Yahoo.';
      } else {
        chartError = _friendly(e);
      }
    } catch (_) {
      bars = const [];
      indicators = IndicatorPack.empty;
      chartError = 'Cannot reach $baseUrl. Start ./start.sh on this Mac.';
    } finally {
      loadingChart = false;
      notifyListeners();
    }
  }

  Future<void> fetchFromYahoo([String? symbol]) async {
    final sym = (symbol ?? selectedSymbol)?.toUpperCase();
    if (sym == null) return;
    fetching = true;
    chartError = null;
    error = null;
    throttleMessage = null;
    notifyListeners();
    try {
      await api.fetchSymbol(sym);
      await loadChart(sym);
      await loadWatchlist();
    } on ApiException catch (e) {
      if (e.isThrottle) {
        throttleMessage =
            e.message.isEmpty ? 'Yahoo is rate-limiting. Try again in a minute.' : e.message;
      } else {
        chartError = _friendly(e);
      }
    } finally {
      fetching = false;
      notifyListeners();
    }
  }

  Future<void> loadNews({String? symbol}) async {
    loadingNews = true;
    notifyListeners();
    try {
      news = await api.getNews(symbol: symbol);
    } on ApiException catch (e) {
      news = NewsFeed(articles: const [], message: _friendly(e));
    } catch (_) {
      news = NewsFeed(
        articles: const [],
        message: 'Cannot reach $baseUrl for headlines.',
      );
    } finally {
      loadingNews = false;
      notifyListeners();
    }
  }

  Future<void> loadScans() async {
    loadingScans = true;
    scanError = null;
    notifyListeners();
    try {
      final results = await Future.wait([
        api.getTrendScan(desk: true, freq: 'daily'),
        api.getScanner(universe: false),
        api.getSetupScan(universe: false),
        api.getScannerStatus(),
      ]);
      trendScan = results[0] as List<TrendScanRow>;
      metricScan = results[1] as List<ScannerRow>;
      setupScan = results[2] as List<SetupScanRow>;
      scannerStatus = results[3] as Map<String, dynamic>;
    } on ApiException catch (e) {
      scanError = _friendly(e);
    } catch (_) {
      scanError = 'Cannot reach $baseUrl for scans.';
    } finally {
      loadingScans = false;
      notifyListeners();
    }
  }

  void setScanMode(String mode) {
    if (mode != 'trend' && mode != 'metrics' && mode != 'setups') return;
    scanMode = mode;
    notifyListeners();
  }

  String _friendly(ApiException e) {
    if (e.isThrottle) {
      return e.message;
    }
    if (e.message.contains('Failed host lookup') ||
        e.message.contains('Connection refused') ||
        e.message.contains('ClientException')) {
      return 'Cannot reach $baseUrl. On a Mac, run ./start.sh then use 127.0.0.1:8050 in Simulator.';
    }
    if (e.message.contains('no such table')) {
      return 'Database is not initialized. Restart ./start.sh on this Mac (same folder as finance.db).';
    }
    return e.message;
  }
}
