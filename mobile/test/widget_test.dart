import 'dart:convert';

import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:whats_news/data/api_client.dart';
import 'package:whats_news/data/app_state.dart';
import 'package:whats_news/data/models.dart';
import 'package:whats_news/main.dart';
import 'package:whats_news/ui/book_page.dart';
import 'package:whats_news/ui/scans_page.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  setUp(() {
    SharedPreferences.setMockInitialValues({});
  });

  testWidgets('watchlist, chart close, and Yahoo headline render from API JSON',
      (tester) async {
    final client = MockClient((request) async {
      final path = request.url.path;
      if (path == '/api/health') {
        return _json({'ok': true, 'service': 'whats-news'});
      }
      if (path == '/api/symbols') {
        return _json([
          {'symbol': 'AAPL', 'name': 'Apple Inc', 'group_tag': ''},
        ]);
      }
      if (path.startsWith('/api/indicators/')) {
        return _json({
          'kama_20': [
            {'date': '2026-01-02', 'value': 104.0},
            {'date': '2026-01-03', 'value': 106.0},
          ],
        });
      }
      if (path == '/api/trend-scan' || path == '/api/scanner' || path == '/api/scanner/status') {
        return _json(path == '/api/scanner/status' ? {'running': false} : []);
      }
      if (path == '/api/setups/scan') {
        return _json({'results': [], 'count': 0});
      }
      if (path == '/api/portfolio/snapshot') {
        return _json({
          'count': 1,
          'ready_count': 0,
          'symbols': [],
          'breakout_queue': [],
          'heatmap': [],
          'group_rollup': [],
        });
      }
      if (path == '/api/sleeves') {
        return _json({
          'sleeves': [
            {
              'id': 'core',
              'label': 'Core indices',
              'group_tag': 'sleeve:core',
              'tickers': ['SPY', 'QQQ', 'IWM'],
            }
          ],
          'note': 'ETF',
        });
      }
      if (path == '/api/macro/board') {
        return _json({
          'regime': {'ready': false, 'note': 'No stored ^VIX/VIX bars — regime line omitted (not invented).'},
          'sleeves': [],
          'note': 'Yahoo / SQLite only.',
        });
      }
      if (path == '/api/edges/board') {
        return _json({
          'regime': {'ready': false},
          'online': [],
          'sections': [],
          'setup_buckets': {},
          'note': 'No screenshot win rates.',
        });
      }
      if (path == '/api/alpaca/status' || path == '/api/alpaca/sync') {
        return _json({
          'configured': false,
          'paper': true,
          'note': 'Alpaca paper — not live P&L',
          'reason': 'Missing APCA_API_KEY_ID / APCA_API_SECRET_KEY. Env only — Alpaca paper, not live P&L.',
          'ok': false,
          'positions': [],
        });
      }
      if (path == '/api/book/pnl' || path == '/api/book/positions') {
        return _json({
          'ready': false,
          'desk_name': 'Whats-News',
          'today_pnl': null,
          'today_pnl_pct': null,
          'nav': null,
          'exposure': {'gross': 0, 'long': 0, 'short': 0, 'net': 0},
          'positions': [],
          'tape': [],
          'equity_curve': [],
          'message': 'Empty paper book. Import a Fidelity Positions CSV or add a line.',
        });
      }
      if (path == '/api/finviz/settings' || path == '/api/finviz/presets') {
        return _json({
          'enabled': true,
          'ttl_sec': 3600,
          'presets': [],
          'filter_docs': {},
        });
      }
      if (path == '/api/finviz/screener' || path.startsWith('/api/finviz/quote/')) {
        return _json({'ready': false, 'rows': [], 'news': [], 'reason': 'fixture'});
      }
      if (path.startsWith('/api/engine/')) {
        return _json({
          'ready': false,
          'rows': [],
          'counts': {},
          'engine_counts': {},
          'daily': {'counts': {}, 'rows': {}},
          'weekly': {'counts': {}, 'rows': {}},
          'strongest': [],
          'breakdowns': [],
          'stretched': [],
          'compressed': [],
          'accelerating': [],
          'fading': [],
          'sectors': [],
          'pullbacks': [],
          'opportunity': [],
          'nav': ['command', 'setup', 'pattern', 'rsi_c', 'macro', 'sigma', 'book', 'chart'],
          'formulas': {'engine': 'NO TRADE if <55 bars', 'rsi_c': 'Wilder RSI(2)..RSI(21)'},
          'message': 'Empty ENGINE — no stored daily bars.',
          'note': 'Yahoo/SQLite OHLCV only.',
          'howto': 'HOW TO READ — ENGINE state machine',
        });
      }
      if (path == '/api/scans/pack' || path == '/api/scans/breadth') {
        return _json({
          'ready': false,
          'lens': 'all',
          'count': 0,
          'scanned': 0,
          'rows': [],
          'n': 0,
          'pct_above_sma50': null,
          'pct_above_sma200': null,
          'message': 'Empty universe — no stored bars to score.',
          'note': 'Stockbee-style breadth idea from our Yahoo/SQLite universe.',
          'oneil_note': 'price/RS only — no fundamentals feed',
          'vcp_note': 'honest proxy, not certified VCP',
        });
      }
      if (path == '/api/hmm/status' || path == '/api/hmm/regime' || path == '/api/hmm/scan' || path == '/api/hmm/combo') {
        return _json({
          'available': false,
          'research_label': true,
          'note': 'research label, not edge',
          'rows': [],
          'states': [],
          'current_probs': [],
        });
      }
      if (path == '/api/fractal/status' || path == '/api/fractal/scan') {
        return _json({
          'available': true,
          'source': 'whats-news fractal_scan (SPEC 25/27)',
          'reason': 'Independent SPEC 25/27 rebuild.',
          'expected': 'whats-news fractal_scan (SPEC 25/27)',
          'columns': ['symbol', 'd_65d', 'd_130d', 'move_65d', 'move_130d', 'read', 'tags'],
          'rows': [],
        });
      }
      if (path.startsWith('/api/pm-desk/') || path.startsWith('/api/spy-rs/')) {
        return _json({'ready': false});
      }
      if (path.startsWith('/api/ohlcv/')) {
        return _json([
          {
            'date': '2026-01-02',
            'open': 100.0,
            'high': 110.0,
            'low': 99.0,
            'close': 108.5,
            'volume': 1000000.0,
          },
          {
            'date': '2026-01-03',
            'open': 108.5,
            'high': 112.0,
            'low': 107.0,
            'close': 111.0,
            'volume': 1200000.0,
          },
        ]);
      }
      if (path == '/api/news' || path.startsWith('/api/news/')) {
        return _json({
          'articles': [
            {
              'symbol': 'AAPL',
              'title': 'Apple hits new high',
              'url': 'https://example.com/apple1',
              'publish_time': '2026-08-21T10:00:00Z',
              'provider': 'Test News',
              'summary': 'Apple stock reaches record',
            }
          ],
          'source': 'Yahoo Finance',
        });
      }
      return _json({'error': 'unhandled ${request.method} $path'}, 404);
    });

    final state = WhatsNewsState(
      api: WhatsNewsApi(
        baseUrl: 'http://127.0.0.1:8050',
        httpClient: client,
      ),
    );

    await tester.pumpWidget(WhatsNewsApp(state: state));
    await tester.pumpAndSettle();

    expect(find.text('Watchlist'), findsWidgets);
    expect(find.text('Scans'), findsWidgets);
    expect(find.text('AAPL'), findsOneWidget);
    expect(find.text('Paper / local only — no live trading.'), findsOneWidget);

    await tester.tap(find.text('AAPL'));
    await tester.pumpAndSettle();

    expect(find.text('111.00'), findsOneWidget);
    expect(find.text('Fetch from Yahoo'), findsOneWidget);

    await tester.tap(find.byIcon(CupertinoIcons.doc_text));
    await tester.pumpAndSettle();

    expect(find.text('Apple hits new high'), findsOneWidget);
    expect(find.text('Test News'), findsOneWidget);
  });

  testWidgets('warnings takeaways ellipsize on a 320pt phone', (tester) async {
    tester.view.physicalSize = const Size(960, 2070);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final state = WhatsNewsState(
      api: WhatsNewsApi(baseUrl: 'http://127.0.0.1:8050', httpClient: MockClient((_) async {
        return _json({'error': 'unused'}, 404);
      })),
    );
    state.scanMode = 'warnings';
    state.warningsBoard = const WarningsBoard(
      ready: true,
      takeaways: [
        WarningHit(
          symbol: 'NVDA',
          label: 'breaking up',
          patternD: 'Breakout',
          vcp: 'BREAK ↑',
          rsiC: 'TREND ↑ STRONG',
          takeaway: 'LONG — VCP BREAK ↑ — RSI-C TREND ↑ — TMS SOLID + (ACCEL +)',
        ),
      ],
    );

    await tester.pumpWidget(CupertinoApp(
      home: SizedBox(
        width: 320,
        height: 690,
        child: ScansPage(state: state, onOpenChart: (_) {}),
      ),
    ));
    await tester.pump();
    expect(tester.takeException(), isNull);
    expect(find.text('NVDA'), findsWidgets);
    expect(find.text('Takeaways (1)'), findsOneWidget);
  });

  testWidgets('risk ranked rows sit tight under the pane chips', (tester) async {
    tester.view.physicalSize = const Size(960, 2070);
    tester.view.devicePixelRatio = 3;
    addTearDown(tester.view.resetPhysicalSize);
    addTearDown(tester.view.resetDevicePixelRatio);

    final state = WhatsNewsState(
      api: WhatsNewsApi(baseUrl: 'http://127.0.0.1:8050', httpClient: MockClient((_) async {
        return _json({'error': 'unused'}, 404);
      })),
    );
    state.bookPane = 'risk';
    state.bookPnl = const BookPnl(
      ready: true,
      risk: RiskPack(
        ready: true,
        thin: false,
        nNames: 3,
        overlapDays: 60,
        vol60: 18.2,
        names: [
          RiskName(symbol: 'AAPL', weightPct: 40, vol20: 20, vol60: 22, pctVar: 41.2),
          RiskName(symbol: 'MSFT', weightPct: 35, vol20: 18, vol60: 19, pctVar: 33.1),
          RiskName(symbol: 'NVDA', weightPct: 25, vol20: 40, vol60: 38, pctVar: 25.7),
        ],
        clusters: [
          RiskCluster(id: 1, members: ['AAPL', 'MSFT'], regime: 'COLD', pctVar: 74.3),
        ],
      ),
    );

    await tester.pumpWidget(CupertinoApp(
      home: SizedBox(
        width: 320,
        height: 690,
        child: BookPage(state: state, onOpenChart: (_) {}),
      ),
    ));
    await tester.pump();
    expect(tester.takeException(), isNull);
    expect(find.textContaining('AAPL'), findsWidgets);
    expect(find.textContaining('C1'), findsOneWidget);
    final chipBottom = tester.getBottomLeft(find.text('Risk')).dy;
    final rowTop = tester.getTopLeft(find.textContaining('%VaR 41.2')).dy;
    expect(rowTop - chipBottom, lessThan(16));
    expect(rowTop - chipBottom, greaterThanOrEqualTo(8));
  });

  test('watchlist maps no-such-table to a restart hint', () async {
    final client = MockClient((request) async {
      return _json({'error': 'no such table: symbols'}, 500);
    });
    final state = WhatsNewsState(
      api: WhatsNewsApi(
        baseUrl: 'http://127.0.0.1:8050',
        httpClient: client,
      ),
    );
    await state.loadWatchlist();
    expect(state.error, contains('Database is not initialized'));
  });
}

http.Response _json(Object body, [int status = 200]) {
  return http.Response(
    jsonEncode(body),
    status,
    headers: {'content-type': 'application/json'},
  );
}
