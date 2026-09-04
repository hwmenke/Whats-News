import 'package:flutter/cupertino.dart';
import 'package:flutter/services.dart';

import 'data/app_state.dart';
import 'ui/chart_page.dart';
import 'ui/news_page.dart';
import 'ui/scans_page.dart';
import 'ui/settings_sheet.dart';
import 'ui/theme.dart';
import 'ui/watchlist_page.dart';

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(WhatsNewsApp(state: WhatsNewsState()));
}

class WhatsNewsApp extends StatelessWidget {
  const WhatsNewsApp({super.key, required this.state});

  final WhatsNewsState state;

  @override
  Widget build(BuildContext context) {
    return CupertinoApp(
      title: 'Whats-News',
      debugShowCheckedModeBanner: false,
      theme: deskCupertinoTheme(),
      home: AnnotatedRegion<SystemUiOverlayStyle>(
        value: SystemUiOverlayStyle.light,
        child: _Shell(state: state),
      ),
    );
  }
}

class _Shell extends StatefulWidget {
  const _Shell({required this.state});

  final WhatsNewsState state;

  @override
  State<_Shell> createState() => _ShellState();
}

class _ShellState extends State<_Shell> {
  late final CupertinoTabController _tabs;

  WhatsNewsState get state => widget.state;

  @override
  void initState() {
    super.initState();
    _tabs = CupertinoTabController(initialIndex: 0);
    state.addListener(_onState);
    _boot();
  }

  Future<void> _boot() async {
    await state.loadSavedBaseUrl();
    await state.refreshAll();
    if (state.selectedSymbol != null) {
      await state.loadChart(state.selectedSymbol!);
    }
  }

  void _onState() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    state.removeListener(_onState);
    _tabs.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return CupertinoTabScaffold(
      controller: _tabs,
      backgroundColor: DeskColors.bg,
      tabBar: CupertinoTabBar(
        backgroundColor: DeskColors.elevated,
        inactiveColor: DeskColors.muted,
        onTap: (i) {
          if (i == 1 && state.selectedSymbol != null && state.bars.isEmpty) {
            state.loadChart(state.selectedSymbol!);
          }
          if (i == 2) {
            state.loadScans();
          }
          if (i == 3) {
            state.loadNews();
          }
        },
        items: const [
          BottomNavigationBarItem(
            icon: Icon(CupertinoIcons.list_bullet),
            label: 'Watchlist',
          ),
          BottomNavigationBarItem(
            icon: Icon(CupertinoIcons.chart_bar_alt_fill),
            label: 'Chart',
          ),
          BottomNavigationBarItem(
            icon: Icon(CupertinoIcons.list_dash),
            label: 'Scans',
          ),
          BottomNavigationBarItem(
            icon: Icon(CupertinoIcons.doc_text),
            label: 'News',
          ),
        ],
      ),
      tabBuilder: (context, index) {
        final Widget page;
        switch (index) {
          case 0:
            page = WatchlistPage(
              state: state,
              onOpenChart: (sym) {
                state.selectSymbol(sym);
                _tabs.index = 1;
              },
              onOpenSettings: () => showServerSheet(context, state),
            );
          case 1:
            page = ChartPage(state: state);
          case 2:
            page = ScansPage(
              state: state,
              onOpenChart: (sym) {
                state.selectSymbol(sym);
                _tabs.index = 1;
              },
            );
          default:
            page = NewsPage(state: state);
        }
        return ColoredBox(color: DeskColors.bg, child: page);
      },
    );
  }
}
