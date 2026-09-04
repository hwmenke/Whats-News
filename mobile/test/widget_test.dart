import 'dart:convert';

import 'package:flutter/cupertino.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:whats_news/data/api_client.dart';
import 'package:whats_news/data/app_state.dart';
import 'package:whats_news/main.dart';

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
