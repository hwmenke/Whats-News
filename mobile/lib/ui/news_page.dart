import 'package:flutter/cupertino.dart';
import 'package:url_launcher/url_launcher.dart';

import '../data/app_state.dart';
import '../data/models.dart';
import 'theme.dart';

class NewsPage extends StatelessWidget {
  const NewsPage({super.key, required this.state});

  final WhatsNewsState state;

  @override
  Widget build(BuildContext context) {
    final feed = state.news;
    return CustomScrollView(
      slivers: [
        CupertinoSliverNavigationBar(
          backgroundColor: DeskColors.elevated,
          largeTitle: const Text('News'),
          trailing: CupertinoButton(
            padding: EdgeInsets.zero,
            onPressed: state.loadingNews ? null : () => state.loadNews(),
            child: const Icon(CupertinoIcons.refresh),
          ),
        ),
        SliverToBoxAdapter(
          child: Padding(
            padding: const EdgeInsets.fromLTRB(16, 8, 16, 4),
            child: Text(
              feed.source.isEmpty
                  ? 'Yahoo Finance headlines for your watchlist'
                  : '${feed.source} · watchlist headlines (real stories, no placeholders)',
              style: const TextStyle(color: DeskColors.muted, fontSize: 12),
            ),
          ),
        ),
        if (state.loadingNews && feed.articles.isEmpty)
          const SliverFillRemaining(
            child: Center(child: CupertinoActivityIndicator()),
          )
        else if (feed.articles.isEmpty)
          SliverFillRemaining(
            hasScrollBody: false,
            child: Padding(
              padding: const EdgeInsets.all(24),
              child: Text(
                feed.message ??
                    'No headlines yet. Add symbols on Watchlist, then refresh.',
                style: const TextStyle(color: DeskColors.muted),
              ),
            ),
          )
        else
          SliverPadding(
            padding: const EdgeInsets.only(bottom: 24),
            sliver: SliverList.separated(
              itemCount: feed.articles.length,
              separatorBuilder: (_, _) => const Padding(
                padding: EdgeInsets.symmetric(horizontal: 16),
                child: ColoredBox(
                  color: DeskColors.border,
                  child: SizedBox(height: 0.5),
                ),
              ),
              itemBuilder: (context, i) => _ArticleTile(article: feed.articles[i]),
            ),
          ),
      ],
    );
  }
}

class _ArticleTile extends StatelessWidget {
  const _ArticleTile({required this.article});

  final NewsArticle article;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: () async {
        if (article.url.isEmpty) return;
        final uri = Uri.tryParse(article.url);
        if (uri != null) {
          await launchUrl(uri, mode: LaunchMode.externalApplication);
        }
      },
      child: Padding(
        padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                if (article.symbol != null)
                  Container(
                    margin: const EdgeInsets.only(right: 8),
                    padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
                    decoration: BoxDecoration(
                      color: DeskColors.accent.withValues(alpha: 0.2),
                      borderRadius: BorderRadius.circular(4),
                    ),
                    child: Text(
                      article.symbol!,
                      style: const TextStyle(
                        color: DeskColors.accentBright,
                        fontSize: 11,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                Expanded(
                  child: Text(
                    article.provider,
                    style: const TextStyle(color: DeskColors.muted, fontSize: 12),
                  ),
                ),
                Text(
                  _when(article.publishTime),
                  style: const TextStyle(color: DeskColors.dim, fontSize: 11),
                ),
              ],
            ),
            const SizedBox(height: 6),
            Text(
              article.title,
              style: const TextStyle(
                color: DeskColors.text,
                fontSize: 16,
                fontWeight: FontWeight.w600,
                height: 1.25,
              ),
            ),
            if (article.summary.isNotEmpty) ...[
              const SizedBox(height: 4),
              Text(
                article.summary,
                maxLines: 3,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(color: DeskColors.muted, fontSize: 13),
              ),
            ],
          ],
        ),
      ),
    );
  }

  static String _when(String iso) {
    if (iso.isEmpty) return '';
    final dt = DateTime.tryParse(iso);
    if (dt == null) return iso;
    final local = dt.toLocal();
    final now = DateTime.now();
    final diff = now.difference(local);
    if (diff.inMinutes < 1) return 'now';
    if (diff.inMinutes < 60) return '${diff.inMinutes}m';
    if (diff.inHours < 24) return '${diff.inHours}h';
    if (diff.inDays < 7) return '${diff.inDays}d';
    return '${local.year}-${local.month.toString().padLeft(2, '0')}-${local.day.toString().padLeft(2, '0')}';
  }
}
