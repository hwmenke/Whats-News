import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:whats_news/data/api_client.dart';
import 'package:whats_news/data/models.dart';

void main() {
  test('WatchSymbol.fromJson reads desk fields', () {
    final s = WatchSymbol.fromJson({
      'symbol': 'aapl',
      'name': 'Apple',
      'group_tag': '',
    });
    expect(s.symbol, 'AAPL');
    expect(s.isUniverseArchive, isFalse);
  });

  test('universe archive tag is detected', () {
    final s = WatchSymbol.fromJson({'symbol': 'ZZ', 'group_tag': 'univ:sp500'});
    expect(s.isUniverseArchive, isTrue);
  });

  test('OhlcvBar.fromJson and NewsArticle match Dash JSON', () {
    final bar = OhlcvBar.fromJson({
      'date': '2026-01-02',
      'open': 100,
      'high': 110,
      'low': 99,
      'close': 108,
      'volume': 1000000,
    });
    expect(bar.isUp, isTrue);
    expect(bar.close, 108);

    final article = NewsArticle.fromJson({
      'symbol': 'AAPL',
      'title': 'Apple hits new high',
      'url': 'https://example.com/apple1',
      'publish_time': '2026-08-21T10:00:00Z',
      'provider': 'Test News',
      'summary': 'Apple stock reaches record',
    });
    expect(article.symbol, 'AAPL');
    expect(article.title, 'Apple hits new high');
  });

  test('WhatsNewsApi listSymbols, ohlcv, news against mock Flask JSON', () async {
    final client = MockClient((request) async {
      final path = request.url.path;
      if (path == '/api/symbols') {
        expect(request.url.queryParameters['desk'], '1');
        return http.Response(
          jsonEncode([
            {'symbol': 'AAPL', 'name': 'Apple', 'group_tag': ''},
          ]),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      if (path == '/api/ohlcv/AAPL') {
        expect(request.url.queryParameters['freq'], 'daily');
        return http.Response(
          jsonEncode([
            {
              'date': '2026-01-02',
              'open': 100,
              'high': 110,
              'low': 99,
              'close': 108,
              'volume': 1000000,
            }
          ]),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      if (path == '/api/news') {
        return http.Response(
          jsonEncode({
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
            'article_count': 1,
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      if (path == '/api/fetch/AAPL' && request.method == 'POST') {
        return http.Response(
          jsonEncode({'symbol': 'AAPL', 'daily_rows': 10, 'weekly_rows': 2}),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      return http.Response(jsonEncode({'error': 'nope'}), 404);
    });

    final api = WhatsNewsApi(
      baseUrl: 'http://127.0.0.1:8050',
      httpClient: client,
    );
    final symbols = await api.listSymbols();
    expect(symbols.single.symbol, 'AAPL');

    final bars = await api.getOhlcv('AAPL');
    expect(bars.single.close, 108);

    final news = await api.getNews();
    expect(news.source, 'Yahoo Finance');
    expect(news.articles.single.title, 'Apple hits new high');

    final fetched = await api.fetchSymbol('aapl');
    expect(fetched['daily_rows'], 10);
  });

  test('Yahoo throttle surfaces code and retry', () async {
    final client = MockClient((request) async {
      return http.Response(
        jsonEncode({
          'error': 'Yahoo is rate-limiting. Try again in a minute.',
          'code': 'yahoo_throttle',
          'retry_after_sec': 60,
        }),
        429,
        headers: {'content-type': 'application/json'},
      );
    });
    final api = WhatsNewsApi(httpClient: client);
    try {
      await api.fetchSymbol('AAPL');
      fail('expected ApiException');
    } on ApiException catch (e) {
      expect(e.isThrottle, isTrue);
      expect(e.retryAfterSec, 60);
    }
  });

  test('indicators and trend-scan parse Flask JSON', () async {
    final client = MockClient((request) async {
      final path = request.url.path;
      if (path == '/api/indicators/AAPL') {
        return http.Response(
          jsonEncode({
            'kama_20': [
              {'date': '2026-01-02', 'value': 104.0},
            ],
          }),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      if (path == '/api/trend-scan') {
        expect(request.url.queryParameters['desk'], '1');
        return http.Response(
          jsonEncode([
            {
              'symbol': 'aapl',
              'price': 211.15,
              'rsi': 62.4,
              'kama20_pct': 1.2,
              'signal': 2,
            }
          ]),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      if (path == '/api/scanner') {
        expect(request.url.queryParameters['universe'], '0');
        return http.Response(
          jsonEncode([
            {
              'symbol': 'AAPL',
              'price': 211.15,
              'chg': 0.4,
              'd': {'rsi_14': 55.0, 'atr_pct': 1.8},
            }
          ]),
          200,
          headers: {'content-type': 'application/json'},
        );
      }
      return http.Response(jsonEncode({'error': 'nope'}), 404);
    });
    final api = WhatsNewsApi(httpClient: client);
    final pack = await api.getIndicators('AAPL');
    expect(pack.of('kama_20').single.value, 104.0);

    final trend = await api.getTrendScan();
    expect(trend.single.symbol, 'AAPL');
    expect(trend.single.rsi, 62.4);

    final metrics = await api.getScanner();
    expect(metrics.single.daily.rsi14, 55.0);
  });

  test('missing OHLCV is 404', () async {
    final client = MockClient((request) async {
      return http.Response(
        jsonEncode({'error': 'No data. Fetch the symbol first.'}),
        404,
        headers: {'content-type': 'application/json'},
      );
    });
    final api = WhatsNewsApi(httpClient: client);
    try {
      await api.getOhlcv('MSFT');
      fail('expected ApiException');
    } on ApiException catch (e) {
      expect(e.isMissingBars, isTrue);
    }
  });
}
