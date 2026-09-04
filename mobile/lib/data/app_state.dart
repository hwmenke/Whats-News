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
  NewsFeed news = const NewsFeed(articles: []);

  bool loadingWatchlist = false;
  bool loadingChart = false;
  bool loadingNews = false;
  bool fetching = false;
  String? error;
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

  double? get sessionChangePct {
    if (bars.length < 2) return null;
    final prev = bars[bars.length - 2].close;
    if (prev == 0) return null;
    return (bars.last.close - prev) / prev * 100;
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
    notifyListeners();
    await Future.wait([
      loadChart(selectedSymbol!),
      loadNews(symbol: selectedSymbol),
    ]);
  }

  Future<void> setFreq(String next) async {
    if (next != 'daily' && next != 'weekly') return;
    freq = next;
    notifyListeners();
    if (selectedSymbol != null) {
      await loadChart(selectedSymbol!);
    }
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
      }
      await loadWatchlist();
    } on ApiException catch (e) {
      error = _friendly(e);
      notifyListeners();
    }
  }

  Future<void> loadChart(String symbol) async {
    loadingChart = true;
    error = null;
    notifyListeners();
    try {
      bars = await api.getOhlcv(symbol, freq: freq);
      throttleMessage = null;
    } on ApiException catch (e) {
      bars = const [];
      if (e.isMissingBars) {
        error = 'No bars stored for $symbol yet. Tap Fetch from Yahoo.';
      } else {
        error = _friendly(e);
      }
    } catch (_) {
      bars = const [];
      error = 'Cannot reach $baseUrl. Start ./start.sh on this Mac.';
    } finally {
      loadingChart = false;
      notifyListeners();
    }
  }

  Future<void> fetchFromYahoo([String? symbol]) async {
    final sym = (symbol ?? selectedSymbol)?.toUpperCase();
    if (sym == null) return;
    fetching = true;
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
        error = _friendly(e);
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
