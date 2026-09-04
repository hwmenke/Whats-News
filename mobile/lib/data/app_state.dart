import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'api_client.dart';
import 'models.dart';

const kApiBasePref = 'whats-news-api-base';
const kPrefFreq = 'whats-news-chart-freq';
const kPrefScanMode = 'whats-news-scan-mode';
const kPrefKama10 = 'whats-news-ov-kama10';
const kPrefKama20 = 'whats-news-ov-kama20';
const kPrefKama50 = 'whats-news-ov-kama50';
const kPrefBb = 'whats-news-ov-bb';
const kPrefEma10 = 'whats-news-ov-ema10';
const kPrefEma20 = 'whats-news-ov-ema20';
const kPrefMacroOpen = 'whats-news-macro-open';

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
  String scanMode = 'qulla';
  String qullaFilter = 'all';
  String groupFilter = '';
  Map<String, dynamic> scannerStatus = const {};

  PortfolioSnapshot snapshot = PortfolioSnapshot.empty;
  DeskNote deskNote = DeskNote.empty;
  SpyRs spyRs = SpyRs.empty;
  List<Sleeve> sleeves = const [];
  MacroBoard macroBoard = MacroBoard.empty;
  EdgesBoard edgesBoard = EdgesBoard.empty;
  FractalStatus fractalStatus = FractalStatus.empty;
  bool macroOpen = true;
  String familyFilter = '';
  bool seedingUniverse = false;

  bool showKama10 = false;
  bool showKama20 = true;
  bool showKama50 = false;
  bool showBollinger = false;
  bool showEma10 = false;
  bool showEma20 = false;

  OhlcvBar? scrubBar;

  bool loadingWatchlist = false;
  bool loadingChart = false;
  bool loadingNews = false;
  bool loadingScans = false;
  bool loadingMacro = false;
  bool seedingSleeve = false;
  bool fetching = false;
  String? error;
  String? chartError;
  String? scanError;
  String? throttleMessage;
  Map<String, dynamic> health = const {};
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

  List<WatchSymbol> get visibleSymbols {
    var rows = symbols;
    if (familyFilter.isNotEmpty) {
      rows = [for (final s in rows) if (s.filterFamily == familyFilter) s];
    }
    if (groupFilter.isEmpty) return rows;
    return [for (final s in rows) if (s.groupTag == groupFilter) s];
  }

  List<String> get deskGroups {
    final seen = <String>{};
    final out = <String>[];
    for (final s in symbols) {
      if (s.groupTag.isEmpty || seen.contains(s.groupTag)) continue;
      seen.add(s.groupTag);
      out.add(s.groupTag);
    }
    out.sort();
    return out;
  }

  List<SetupScanRow> get qullaRows {
    var rows = [
      for (final r in setupScan)
        if (r.isQullaCandidate && _inGroup(r.symbol)) r,
    ];
    switch (qullaFilter) {
      case 'ep':
        rows = [for (final r in rows) if (r.isEp) r];
      case 'breakout':
        rows = [for (final r in rows) if (r.isBreakoutQueue) r];
      case 'vol':
        rows = [for (final r in rows) if (r.isVolSurge) r];
      case 'adr':
        rows = [for (final r in rows) if (r.isHighAdr) r];
    }
    rows.sort((a, b) {
      final sa = b.setupScore ?? 0;
      final sb = a.setupScore ?? 0;
      if (sa != sb) return sa.compareTo(sb);
      return (b.adrPct ?? 0).compareTo(a.adrPct ?? 0);
    });
    return rows;
  }

  SetupScanRow? setupFor(String symbol) {
    final key = symbol.toUpperCase();
    for (final r in setupScan) {
      if (r.symbol == key) return r;
    }
    return null;
  }

  bool _inGroup(String symbol) {
    if (groupFilter.isEmpty) return true;
    for (final s in symbols) {
      if (s.symbol == symbol) return s.groupTag == groupFilter;
    }
    return false;
  }

  double? get sessionChangePct {
    final bar = displayBar;
    if (bar == null || bars.length < 2) return null;
    final idx = bars.indexWhere((b) => b.date == bar.date);
    if (idx < 1) return null;
    final prev = bars[idx - 1].close;
    if (prev == 0) return null;
    return (bar.close - prev) / prev * 100;
  }

  Future<void> loadSavedPrefs() async {
    final prefs = await SharedPreferences.getInstance();
    final saved = prefs.getString(kApiBasePref);
    if (saved != null && saved.trim().isNotEmpty) {
      api.setBaseUrl(saved);
    }
    freq = prefs.getString(kPrefFreq) ?? freq;
    scanMode = prefs.getString(kPrefScanMode) ?? scanMode;
    showKama10 = prefs.getBool(kPrefKama10) ?? showKama10;
    showKama20 = prefs.getBool(kPrefKama20) ?? showKama20;
    showKama50 = prefs.getBool(kPrefKama50) ?? showKama50;
    showBollinger = prefs.getBool(kPrefBb) ?? showBollinger;
    showEma10 = prefs.getBool(kPrefEma10) ?? showEma10;
    showEma20 = prefs.getBool(kPrefEma20) ?? showEma20;
    macroOpen = prefs.getBool(kPrefMacroOpen) ?? macroOpen;
    notifyListeners();
  }

  Future<void> loadSavedBaseUrl() => loadSavedPrefs();

  Future<void> setBaseUrl(String url) async {
    api.setBaseUrl(url);
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(kApiBasePref, api.baseUrl);
    notifyListeners();
  }

  Future<void> _persist() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(kPrefFreq, freq);
    await prefs.setString(kPrefScanMode, scanMode);
    await prefs.setBool(kPrefKama10, showKama10);
    await prefs.setBool(kPrefKama20, showKama20);
    await prefs.setBool(kPrefKama50, showKama50);
    await prefs.setBool(kPrefBb, showBollinger);
    await prefs.setBool(kPrefEma10, showEma10);
    await prefs.setBool(kPrefEma20, showEma20);
    await prefs.setBool(kPrefMacroOpen, macroOpen);
  }

  Future<void> refreshAll() async {
    await Future.wait([
      loadWatchlist(),
      loadNews(),
      loadMacro(),
      pingHealth(),
    ]);
    if (selectedSymbol != null) {
      await loadChart(selectedSymbol!);
    }
  }

  Future<void> pingHealth() async {
    try {
      health = await api.health();
    } catch (_) {
      health = {'ok': false};
    }
    notifyListeners();
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

  Future<void> loadMacro() async {
    loadingMacro = true;
    notifyListeners();
    try {
      snapshot = await api.getPortfolioSnapshot();
    } on ApiException catch (e) {
      snapshot = PortfolioSnapshot(message: _friendly(e));
    } catch (_) {
      snapshot = const PortfolioSnapshot(message: 'Macro unavailable.');
    }
    try {
      sleeves = await api.getSleeves();
    } on ApiException {
      // older servers
    }
    try {
      macroBoard = await api.getMacroBoard();
    } on ApiException {
      macroBoard = MacroBoard.empty;
    }
    try {
      edgesBoard = await api.getEdgesBoard();
    } on ApiException {
      edgesBoard = EdgesBoard.empty;
    }
    try {
      fractalStatus = await api.getFractalStatus();
    } on ApiException {
      fractalStatus = FractalStatus.empty;
    }
    if (selectedSymbol != null) {
      try {
        spyRs = await api.getSpyRs(selectedSymbol!);
      } on ApiException {
        spyRs = SpyRs.empty;
      }
    }
    loadingMacro = false;
    notifyListeners();
  }

  Future<void> selectSymbol(String symbol) async {
    selectedSymbol = symbol.toUpperCase();
    scrubBar = null;
    bars = const [];
    indicators = IndicatorPack.empty;
    deskNote = DeskNote.empty;
    chartError = null;
    notifyListeners();
    await Future.wait([
      loadChart(selectedSymbol!),
      loadNews(symbol: selectedSymbol),
      loadDeskNote(selectedSymbol!),
    ]);
    try {
      spyRs = await api.getSpyRs(selectedSymbol!);
    } catch (_) {
      spyRs = SpyRs.empty;
    }
    notifyListeners();
  }

  Future<void> loadDeskNote(String symbol) async {
    try {
      deskNote = await api.getPmDesk(symbol);
    } on ApiException {
      final row = setupFor(symbol);
      if (row != null) {
        deskNote = DeskNote(
          symbol: row.symbol,
          ready: row.ready,
          regime: row.regime,
          adrPct: row.adrPct,
          dist20dHighPct: row.dist20dHighPct,
          volRatio: row.volRatio,
          isEp: row.isEp,
          isVolSurge: row.isVolSurge,
          isNearHigh: row.setups.contains('NEAR_HIGH'),
          breakoutScore: row.setupScore,
          changePct: row.changePct,
          error: row.error,
        );
      }
    }
    notifyListeners();
  }

  Future<void> setFreq(String next) async {
    if (next != 'daily' && next != 'weekly' && next != 'monthly') return;
    freq = next;
    scrubBar = null;
    notifyListeners();
    await _persist();
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
      case 'ema10':
        showEma10 = !showEma10;
      case 'ema20':
        showEma20 = !showEma20;
    }
    notifyListeners();
    _persist();
  }

  void setGroupFilter(String tag) {
    groupFilter = groupFilter == tag ? '' : tag;
    notifyListeners();
  }

  void setFamilyFilter(String family) {
    familyFilter = familyFilter == family ? '' : family;
    notifyListeners();
  }

  void setQullaFilter(String id) {
    qullaFilter = id;
    notifyListeners();
  }

  void toggleMacro() {
    macroOpen = !macroOpen;
    notifyListeners();
    _persist();
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
      await loadMacro();
    } on ApiException catch (e) {
      error = _friendly(e);
      notifyListeners();
    }
  }

  Future<void> seedSleeve(String id, {bool fetchAnchors = true}) async {
    seedingSleeve = true;
    error = null;
    notifyListeners();
    try {
      await api.seedSleeve(id);
      await loadWatchlist();
      Sleeve? sleeve;
      for (final s in sleeves) {
        if (s.id == id) sleeve = s;
      }
      final tickers = sleeve?.tickers ?? const <String>[];
      final fetchList = fetchAnchors
          ? (tickers.isNotEmpty ? tickers : const ['SPY', 'QQQ'])
          : const <String>[];
      for (final anchor in fetchList) {
        try {
          await api.fetchSymbol(anchor);
          await loadMacro();
        } on ApiException catch (e) {
          if (e.isThrottle) {
            throttleMessage = e.message;
            break;
          }
        }
      }
      await loadWatchlist();
      await loadMacro();
    } on ApiException catch (e) {
      error = _friendly(e);
    } finally {
      seedingSleeve = false;
      notifyListeners();
    }
  }

  Future<void> seedCore50() async {
    seedingSleeve = true;
    error = null;
    notifyListeners();
    try {
      await api.seedCore50();
      await loadWatchlist();
      await loadMacro();
    } on ApiException catch (e) {
      error = _friendly(e);
    } finally {
      seedingSleeve = false;
      notifyListeners();
    }
  }

  Future<void> registerSp500() async {
    seedingUniverse = true;
    error = null;
    notifyListeners();
    try {
      await api.universeSync(indices: const ['sp500']);
      scannerStatus = await api.getScannerStatus();
    } on ApiException catch (e) {
      error = _friendly(e);
    } finally {
      seedingUniverse = false;
      notifyListeners();
    }
  }

  Future<void> fetchVix() async {
    try {
      await api.addSymbol('^VIX');
      await api.fetchSymbol('^VIX');
      await loadMacro();
    } on ApiException catch (e) {
      if (e.isThrottle) {
        throttleMessage = e.message;
      } else {
        error = _friendly(e);
      }
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
        deskNote = DeskNote.empty;
        scrubBar = null;
      }
      await loadWatchlist();
      await loadMacro();
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
      await loadDeskNote(sym);
      await loadMacro();
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
    if (mode != 'qulla' &&
        mode != 'edges' &&
        mode != 'trend' &&
        mode != 'metrics' &&
        mode != 'setups') {
      return;
    }
    scanMode = mode;
    notifyListeners();
    _persist();
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
