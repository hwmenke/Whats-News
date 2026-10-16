"""Executable coverage for untrusted standalone news content."""
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class NewsRenderingTests(unittest.TestCase):
    def test_summary_markup_is_parsed_in_an_inert_document(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node not available')
        script = r'''
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('news.html', 'utf8');
const markup = '<img src=x onerror="alert(1)"><b>Headline summary</b>';
const calls = [];
const ctx = {
    document: {createElement() {throw new Error('Provider HTML reached the live DOM');}},
    DOMParser: class {
        parseFromString(html, type) {
            calls.push([html, type]);
            return {body: {textContent: html === markup ? 'Headline summary' : ''}};
        }
    }
};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('  function stripHtml'),
                            source.indexOf('  function showStatus')), ctx);
assert.strictEqual(ctx.stripHtml(markup), 'Headline summary');
assert.strictEqual(ctx.stripHtml(null), '');
assert.deepStrictEqual(calls, [[markup, 'text/html'], ['', 'text/html']]);
'''
        result = subprocess.run([node, '-e', script], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_provider_content_is_text_and_links_require_http(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node not available')
        script = r'''
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('news.html', 'utf8');
const ctx = {URL, stripHtml: value => value, formatTime: value => value};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('  function escapeNewsHtml'),
                            source.indexOf('  async function loadNews')), ctx);
const attack = '<img src=x onerror="alert(1)">&\'TEST';
const article = {symbol: attack, title: attack, summary: attack, provider: attack,
                 publish_time: attack, url: 'javascript:alert(1)',
                 provider_url: 'data:text/html,<script>alert(1)</script>'};
let html = ctx.renderArticle(article);
assert.ok(!html.includes('<img'));
assert.ok(!html.includes('<a '));
assert.ok(!html.includes('javascript:'));
assert.strictEqual(html.split('&lt;img').length - 1, 5);
assert.ok(html.includes('&quot;alert(1)&quot;'));
assert.ok(html.includes('&amp;&#39;TEST'));
article.url = ' https://example.com/news?a=1&b=2 ';
article.provider_url = 'http://example.com/';
html = ctx.renderArticle(article);
assert.ok(html.includes('href="https://example.com/news?a=1&amp;b=2"'));
assert.ok(html.includes('href="http://example.com/"'));
for (const url of ['" onmouseover="alert(1)', '/relative', {}, null]) {
    assert.strictEqual(ctx.safeNewsUrl(url), '');
}
const empty = ctx.renderEmptyState(attack, attack, {linkDashboard: true});
assert.ok(!empty.includes('<img'));
assert.strictEqual(empty.split('&lt;img').length - 1, 2);
assert.ok(empty.includes('href="/"'));
'''
        result = subprocess.run([node, '-e', script], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)

    def test_book_news_orders_publication_instants_and_keeps_bad_dates_last(self):
        node = shutil.which('node')
        if not node:
            self.skipTest('node not available')
        script = r'''
const assert = require('assert');
const fs = require('fs');
const vm = require('vm');
const source = fs.readFileSync('scripts/app.js', 'utf8');
const articles = [
    {title: 'older offset', url: 'one', publish_time: '2026-10-13T11:00:00+02:00'},
    {title: 'bad date', url: 'two', publish_time: 'not-a-date'},
    {title: 'newer instant', url: 'three', publish_time: '2026-10-13T06:00:00-04:00'},
    {title: 'missing date', url: 'four'},
    {title: 'equal instant', url: 'five', publish_time: '2026-10-13T10:00:00Z'}
];
let rendered;
const ctx = {
    state: {portfolioMeta: {news_focus: ['AAPL', 'MSFT']}},
    URL, API: '/api', switchTab() {}, toast() {},
    document: {getElementById() {return null;}},
    apiFetch: async url => ({articles: url.endsWith('AAPL') ? articles : [articles[2]]}),
    renderNewsArticles(value) {rendered = value;}
};
vm.createContext(ctx);
vm.runInContext(source.slice(source.indexOf('async function openBookNews()'),
                            source.indexOf('function readWatchlistFilter()')), ctx);
(async () => {
    await ctx.openBookNews();
    assert.deepStrictEqual(Array.from(rendered, a => a.title), [
        'newer instant', 'equal instant', 'older offset', 'bad date', 'missing date'
    ]);
    assert.strictEqual(rendered[0].publish_time, articles[2].publish_time);
    assert.strictEqual(rendered[0].symbol, 'AAPL');
    delete ctx.renderNewsArticles;
    const list = {innerHTML: ''};
    ctx.document.getElementById = id => id === 'news-list' ? list : null;
    const attack = '<img src=x onerror="alert(1)">&';
    ctx.state.portfolioMeta.news_focus = [attack];
    const article = {title: attack, provider: attack, publish_time: attack};
    ctx.apiFetch = async () => ({articles: [article]});
    for (const url of ['javascript:alert(1)', 'data:text/html,evil', '/relative',
                       {}, null, '" onmouseover="alert(1)']) {
        article.url = url;
        await ctx.openBookNews();
        assert.ok(!list.innerHTML.includes('<img'));
        assert.ok(list.innerHTML.includes('href="#"'));
        assert.strictEqual(list.innerHTML.split('&lt;img').length - 1, 4);
    }
    article.url = ' https://example.com/news?a=1&b=2 ';
    await ctx.openBookNews();
    assert.ok(list.innerHTML.includes('href="https://example.com/news?a=1&amp;b=2"'));

})().catch(error => {console.error(error); process.exitCode = 1;});
'''
        result = subprocess.run([node, '-e', script], cwd=ROOT,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
