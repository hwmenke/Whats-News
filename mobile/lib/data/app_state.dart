import 'dart:async';

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
const kPrefFamily = 'whats-news-family';
const kPrefRefresh = 'whats-news-refresh-sec';
const kPrefNewsScope = 'whats-news-news-scope';
const kPrefEdgeTag = 'whats-news-edge-tag';
const kPrefQulla = 'whats-news-qulla-filter';

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
  String qullaFilter = 'all';
  String groupFilter = '';
  String newsScope = 'desk';
  String edgeTag = '';
  int refreshSec = 0;
  Timer? _refreshTimer;
  Map<String, dynamic> scannerStatus = const {};

  PortfolioSnapshot snapshot = PortfolioSnapshot.empty;
  DeskNote deskNote = DeskNote.empty;
  SpyRs spyRs = SpyRs.empty;
  List<Sleeve> sleeves = const [];
  MacroBoard macroBoard = MacroBoard.empty;
  MarketMovesBoard marketMoves = MarketMovesBoard.empty;
  EdgesBoard edgesBoard = EdgesBoard.empty;
  FractalStatus fractalStatus = FractalStatus.empty;
  FinvizScreener finvizScreener = FinvizScreener.empty;
  FinvizQuote finvizQuote = FinvizQuote.empty;
  bool finvizEnabled = true;
  int finvizTtlSec = 3600;
  String finvizPreset = 'qulla_momentum';
  HmmRegime hmmRegime = HmmRegime.empty;
  ComboScan comboScan = ComboScan.empty;
  ScanPack scanPack = ScanPack.empty;
  ScanBreadth scanBreadth = ScanBreadth.empty;
  EngineBoard engineCommand = EngineBoard.empty;
  EngineBoard engineBoard = EngineBoard.empty;
  RsiCounterBoard rsiCounter = RsiCounterBoard.empty;
  PatternBoard patternBoard = PatternBoard.empty;
  StretchBoard stretchBoard = StretchBoard.empty;
  SigmaBoard sigmaBoard = SigmaBoard.empty;
  EngineMaps engineMaps = EngineMaps.empty;
  WarningsBoard warningsBoard = WarningsBoard.empty;
  int hmmStates = 2;
  String hmmStateFilter = '';
  String hmmView = 'all';
  BookPnl bookPnl = BookPnl.empty;
  bool loadingBook = false;
  String bookPane = 'pnl';
  String? bookError;
  Map<String, dynamic> alpacaStatus = const {};
  String? alpacaMessage;
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

  List<(String, List<WatchSymbol>)> get groupedVisible {
    final map = <String, List<WatchSymbol>>{};
    final order = <String>[];
    for (final s in visibleSymbols) {
      final key = s.displayGroup;
      if (!map.containsKey(key)) {
        map[key] = [];
        order.add(key);
      }
      map[key]!.add(s);
    }
    return [for (final k in order) (k, map[k]!)];
  }

  List<EdgeInstrument> get filteredEdgeRows {
    final rows = [
      for (final sec in edgesBoard.sections)
        ...sec.rows,
    ];
    if (edgeTag.isEmpty) return rows;
    return [for (final r in rows) if (r.tags.contains(edgeTag)) r];
  }

  List<String> get edgeTags {
    final seen = <String>{};
    final out = <String>[];
    for (final sec in edgesBoard.sections) {
      for (final row in sec.rows) {
        for (final t in row.tags) {
          if (t.isEmpty || seen.contains(t)) continue;
          seen.add(t);
          out.add(t);
        }
      }
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
      case 'high':
        rows = [for (final r in rows) if (r.isNearHigh) r];
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
    familyFilter = prefs.getString(kPrefFamily) ?? familyFilter;
    newsScope = prefs.getString(kPrefNewsScope) ?? newsScope;
    edgeTag = prefs.getString(kPrefEdgeTag) ?? edgeTag;
    qullaFilter = prefs.getString(kPrefQulla) ?? qullaFilter;
    refreshSec = prefs.getInt(kPrefRefresh) ?? refreshSec;
    _armRefresh();
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
    await prefs.setString(kPrefFamily, familyFilter);
    await prefs.setString(kPrefNewsScope, newsScope);
    await prefs.setString(kPrefEdgeTag, edgeTag);
    await prefs.setString(kPrefQulla, qullaFilter);
    await prefs.setInt(kPrefRefresh, refreshSec);
  }

  void _armRefresh() {
    _refreshTimer?.cancel();
    _refreshTimer = null;
    if (refreshSec < 15) return;
    _refreshTimer = Timer.periodic(Duration(seconds: refreshSec), (_) {
      refreshAll();
    });
  }

  void setRefreshSec(int sec) {
    refreshSec = sec < 0 ? 0 : sec;
    _armRefresh();
    notifyListeners();
    _persist();
  }

  void setNewsScope(String scope) {
    newsScope = scope == 'symbol' ? 'symbol' : 'desk';
    notifyListeners();
    _persist();
    loadNews(symbol: newsScope == 'symbol' ? selectedSymbol : null);
  }

  void setBookPane(String pane) {
    const allowed = {'upload', 'positions', 'pnl', 'risk'};
    var next = allowed.contains(pane) ? pane : 'pnl';
    if (next == 'positions') next = 'upload';
    bookPane = next;
    notifyListeners();
    loadBook();
  }

  Future<void> loadBook() async {
    loadingBook = true;
    bookError = null;
    notifyListeners();
    try {
      bookPnl = await api.getBookPnl();
      if (bookPane == 'upload') {
        try {
          alpacaStatus = await api.getAlpacaStatus();
          alpacaMessage = '${alpacaStatus['reason'] ?? alpacaStatus['note'] ?? ''}';
        } on ApiException {
          alpacaStatus = const {};
        }
      }
    } on ApiException catch (e) {
      bookError = _friendly(e);
      bookPnl = BookPnl.empty;
    } catch (_) {
      bookError = 'Cannot reach $baseUrl for the paper book.';
      bookPnl = BookPnl.empty;
    } finally {
      loadingBook = false;
      notifyListeners();
    }
  }

  Future<void> addBookLine(String symbol, double qty, {String side = 'long', double? avgCost}) async {
    await api.addBookPosition(symbol: symbol, qty: qty, side: side, avgCost: avgCost);
    await loadBook();
  }

  Future<void> removeBookLine(int id) async {
    await api.deleteBookPosition(id);
    await loadBook();
  }

  Future<String> syncAlpacaPaper() async {
    try {
      final raw = await api.syncAlpacaPaper();
      if (raw['ok'] == true) {
        alpacaMessage = 'Alpaca paper — not live P&L. Imported ${raw['imported'] ?? 0} lines.';
      } else {
        alpacaMessage = '${raw['reason'] ?? raw['note'] ?? 'Alpaca paper unavailable'}';
      }
      await loadBook();
      return alpacaMessage ?? '';
    } on ApiException catch (e) {
      alpacaMessage = _friendly(e);
      notifyListeners();
      return alpacaMessage ?? '';
    }
  }

  Future<String> importBookCsv(String csv, {bool replace = false}) async {
    final raw = await api.importBookCsv(csv, replace: replace);
    await loadBook();
    if (raw['error'] != null) return '${raw['error']}';
    return 'Imported ${raw['imported'] ?? 0} lines.';
  }

  void setEdgeTag(String tag) {
    edgeTag = edgeTag == tag ? '' : tag;
    notifyListeners();
    _persist();
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
      fractalStatus = await api.getFractalScan();
    } on ApiException {
      try {
        fractalStatus = await api.getFractalStatus();
      } on ApiException {
        fractalStatus = FractalStatus.empty;
      }
    }
    try {
      final s = await api.getFinvizSettings();
      if (s.containsKey('enabled')) finvizEnabled = s['enabled'] == true;
      final ttl = s['ttl_sec'];
      if (ttl is num) finvizTtlSec = ttl.toInt();
    } on ApiException {
      // older servers
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
    _persist();
  }

  void setQullaFilter(String id) {
    qullaFilter = id;
    notifyListeners();
    _persist();
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
      if (fetchAnchors) {
        try {
          await api.seedFetchDesk(core50: false);
        } on ApiException catch (e) {
          if (e.isThrottle) throttleMessage = e.message;
        }
      }
      await loadWatchlist();
      await loadMacro();
      await loadScanBreadth();
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
      await api.seedFetchDesk(core50: true);
      await loadWatchlist();
      await loadMacro();
      await loadScanBreadth();
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
      news = newsScope == 'symbol' && (symbol ?? selectedSymbol) != null
          ? await api.getNews(symbol: symbol ?? selectedSymbol)
          : await api.getNews(desk: true);
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
      try {
        fractalStatus = await api.getFractalScan();
      } on ApiException {
        fractalStatus = FractalStatus.empty;
      }
      if (scanMode == 'finviz') {
        await loadFinviz();
      }
      if (scanMode == 'hmm') {
        await loadHmm();
      }
      if (scanMode == 'combo') {
        await loadCombo();
      }
      await loadScanBreadth();
      if (_isPackMode(scanMode)) {
        await loadScanPack();
      }
      if (_isEngineMode(scanMode)) {
        await loadEngine();
      }
      if (scanMode == 'moves') {
        await loadMarketMoves();
      }
    } on ApiException catch (e) {
      scanError = _friendly(e);
    } catch (_) {
      scanError = 'Cannot reach $baseUrl for scans.';
    } finally {
      loadingScans = false;
      notifyListeners();
    }
  }

  Future<void> loadFinviz({bool force = false}) async {
    try {
      finvizScreener = await api.getFinvizScreener(preset: finvizPreset, force: force);
    } on ApiException {
      finvizScreener = FinvizScreener.empty;
    }
    notifyListeners();
  }

  Future<void> loadFinvizQuote(String symbol) async {
    try {
      finvizQuote = await api.getFinvizQuote(symbol);
    } on ApiException {
      finvizQuote = FinvizQuote.empty;
    }
    notifyListeners();
  }

  Future<void> setFinvizEnabled(bool on) async {
    finvizEnabled = on;
    notifyListeners();
    try {
      final s = await api.setFinvizSettings(enabled: on, ttlSec: finvizTtlSec);
      if (s['enabled'] is bool) finvizEnabled = s['enabled'] == true;
    } on ApiException {
      // keep local
    }
    notifyListeners();
  }

  Future<void> setFinvizTtl(int sec) async {
    finvizTtlSec = sec < 60 ? 60 : (sec > 86400 ? 86400 : sec);
    notifyListeners();
    try {
      await api.setFinvizSettings(enabled: finvizEnabled, ttlSec: finvizTtlSec);
    } on ApiException {
      // keep local
    }
  }

  void setFinvizPreset(String id) {
    if (id.isEmpty) return;
    finvizPreset = id;
    notifyListeners();
    loadFinviz();
  }

  Future<void> loadHmm() async {
    try {
      hmmRegime = await api.getHmmScan(states: hmmStates, state: hmmStateFilter, view: hmmView);
    } on ApiException {
      hmmRegime = HmmRegime.empty;
    }
    notifyListeners();
  }

  bool _isPackMode(String mode) =>
      mode == 'ma' || mode == 'rsi' || mode == 'breakout' || mode == 'oneil' || mode == 'vcp';

  bool _isEngineMode(String mode) =>
      mode == 'command' ||
      mode == 'setup' ||
      mode == 'pattern' ||
      mode == 'rsic' ||
      mode == 'stretch' ||
      mode == 'sigma' ||
      mode == 'maps' ||
      mode == 'warnings';

  Future<void> loadEngine() async {
    try {
      if (scanMode == 'command') {
        engineCommand = await api.getEngineCommand();
        try {
          engineBoard = await api.getEngineBoard();
        } on ApiException {
          engineBoard = EngineBoard.empty;
        }
      } else if (scanMode == 'setup') {
        engineBoard = await api.getEngineBoard();
      } else if (scanMode == 'pattern') {
        patternBoard = await api.getEnginePatterns();
      } else if (scanMode == 'rsic') {
        rsiCounter = await api.getRsiCounter();
      } else if (scanMode == 'stretch') {
        stretchBoard = await api.getEngineStretch();
      } else if (scanMode == 'sigma') {
        sigmaBoard = await api.getEngineSigma();
      } else if (scanMode == 'maps') {
        engineMaps = await api.getEngineMaps();
      } else if (scanMode == 'warnings') {
        warningsBoard = await api.getEngineWarnings();
      }
    } on ApiException {
      if (scanMode == 'command') engineCommand = EngineBoard.empty;
      if (scanMode == 'setup') engineBoard = EngineBoard.empty;
      if (scanMode == 'pattern') patternBoard = PatternBoard.empty;
      if (scanMode == 'rsic') rsiCounter = RsiCounterBoard.empty;
      if (scanMode == 'stretch') stretchBoard = StretchBoard.empty;
      if (scanMode == 'sigma') sigmaBoard = SigmaBoard.empty;
      if (scanMode == 'maps') engineMaps = EngineMaps.empty;
      if (scanMode == 'warnings') warningsBoard = WarningsBoard.empty;
    }
    notifyListeners();
  }

  Future<void> loadScanPack() async {
    try {
      scanPack = await api.getScanPack(lens: _isPackMode(scanMode) ? scanMode : 'all');
      scanBreadth = scanPack.breadth;
    } on ApiException {
      scanPack = ScanPack.empty;
    }
    notifyListeners();
  }

  Future<void> loadScanBreadth() async {
    try {
      scanBreadth = await api.getScanBreadth();
    } on ApiException {
      scanBreadth = ScanBreadth.empty;
    }
    notifyListeners();
  }

  Future<void> loadCombo() async {
    try {
      comboScan = await api.getHmmCombo(states: hmmStates, state: hmmStateFilter);
    } on ApiException {
      comboScan = ComboScan.empty;
    }
    notifyListeners();
  }

  void setHmmView(String view) {
    hmmView = view;
    notifyListeners();
    loadHmm();
  }

  void setHmmStates(int n) {
    hmmStates = n == 3 ? 3 : 2;
    notifyListeners();
    loadHmm();
  }

  void setHmmStateFilter(String label) {
    hmmStateFilter = hmmStateFilter == label ? '' : label;
    notifyListeners();
    loadHmm();
  }

  void setScanMode(String mode) {
    if (mode != 'qulla' &&
        mode != 'edges' &&
        mode != 'trend' &&
        mode != 'metrics' &&
        mode != 'setups' &&
        mode != 'fractal' &&
        mode != 'finviz' &&
        mode != 'hmm' &&
        mode != 'combo' &&
        !_isPackMode(mode) &&
        !_isEngineMode(mode) &&
        mode != 'moves' &&
        mode != 'macro') {
      return;
    }
    scanMode = mode;
    notifyListeners();
    _persist();
    if (mode == 'finviz') loadFinviz();
    if (mode == 'hmm') loadHmm();
    if (mode == 'combo') loadCombo();
    if (_isPackMode(mode)) loadScanPack();
    if (_isEngineMode(mode)) loadEngine();
    if (mode == 'moves') loadMarketMoves();
    if (mode == 'macro') loadMacro();
  }

  Future<void> loadMarketMoves() async {
    try {
      marketMoves = await api.getMarketMoves();
    } on ApiException {
      marketMoves = MarketMovesBoard.empty;
    }
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
