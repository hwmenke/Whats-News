"""Executable coverage for untrusted standalone news content."""
import pathlib
import shutil
import subprocess
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class NewsRenderingTests(unittest.TestCase):
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
