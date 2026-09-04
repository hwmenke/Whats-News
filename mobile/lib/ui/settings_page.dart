import 'package:flutter/cupertino.dart';

import '../data/api_client.dart';
import '../data/app_state.dart';
import 'theme.dart';

Future<void> openSettings(BuildContext context, WhatsNewsState state) {
  return Navigator.of(context, rootNavigator: true).push(
    CupertinoPageRoute<void>(
      builder: (_) => SettingsPage(state: state),
    ),
  );
}

class SettingsPage extends StatefulWidget {
  const SettingsPage({super.key, required this.state});

  final WhatsNewsState state;

  @override
  State<SettingsPage> createState() => _SettingsPageState();
}

class _SettingsPageState extends State<SettingsPage> {
  late final TextEditingController _url;

  @override
  void initState() {
    super.initState();
    _url = TextEditingController(text: widget.state.baseUrl);
    widget.state.pingHealth();
    if (widget.state.sleeves.isEmpty) {
      widget.state.loadMacro();
    }
  }

  @override
  void dispose() {
    _url.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final state = widget.state;
    final health = state.health;
    final schemaOk = health['schema_ok'] == true;
    return CupertinoPageScaffold(
      backgroundColor: DeskColors.bg,
      navigationBar: const CupertinoNavigationBar(
        backgroundColor: DeskColors.elevated,
        middle: Text('Settings'),
      ),
      child: SafeArea(
        child: ListenableBuilder(
          listenable: state,
          builder: (context, _) {
            return ListView(
              padding: const EdgeInsets.fromLTRB(16, 16, 16, 32),
              children: [
                const _SectionTitle('Server'),
                CupertinoTextField(
                  controller: _url,
                  placeholder: kDefaultApiBase,
                  style: const TextStyle(color: DeskColors.text),
                  decoration: BoxDecoration(
                    color: DeskColors.card,
                    borderRadius: BorderRadius.circular(10),
                    border: Border.all(color: DeskColors.border),
                  ),
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
                ),
                const SizedBox(height: 8),
                Text(
                  schemaOk
                      ? 'Connected · schema ok · ${health['symbol_count'] ?? '—'} symbols'
                      : 'Health: ${health['ok'] == true ? 'process up' : 'not reached'}',
                  style: TextStyle(
                    color: schemaOk ? DeskColors.green : DeskColors.muted,
                    fontSize: 12,
                  ),
                ),
                const SizedBox(height: 8),
                CupertinoButton.filled(
                  onPressed: () async {
                    await state.setBaseUrl(_url.text);
                    await state.refreshAll();
                  },
                  child: const Text('Save & reconnect'),
                ),
                const SizedBox(height: 22),
                const _SectionTitle('Refresh'),
                _Seg(
                  value: '${state.refreshSec}',
                  children: const {
                    '0': Text('Off'),
                    '30': Text('30s'),
                    '60': Text('60s'),
                    '120': Text('2m'),
                  },
                  onChanged: (v) => state.setRefreshSec(int.tryParse(v) ?? 0),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Reloads stored Yahoo/SQLite — no invented PX, z, D, or headlines.',
                  style: TextStyle(color: DeskColors.muted, fontSize: 12),
                ),
                const SizedBox(height: 22),
                const _SectionTitle('Chart defaults'),
                _Seg(
                  value: state.freq,
                  children: const {
                    'daily': Text('D'),
                    'weekly': Text('W'),
                    'monthly': Text('M'),
                  },
                  onChanged: state.setFreq,
                ),
                const SizedBox(height: 8),
                Wrap(
                  spacing: 6,
                  runSpacing: 6,
                  children: [
                    _ToggleChip(label: 'KAMA 10', on: state.showKama10, onTap: () => state.toggleOverlay('kama10')),
                    _ToggleChip(label: 'KAMA 20', on: state.showKama20, onTap: () => state.toggleOverlay('kama20')),
                    _ToggleChip(label: 'KAMA 50', on: state.showKama50, onTap: () => state.toggleOverlay('kama50')),
                    _ToggleChip(label: 'EMA 10', on: state.showEma10, onTap: () => state.toggleOverlay('ema10')),
                    _ToggleChip(label: 'EMA 20', on: state.showEma20, onTap: () => state.toggleOverlay('ema20')),
                    _ToggleChip(label: 'BB 20', on: state.showBollinger, onTap: () => state.toggleOverlay('bb')),
                  ],
                ),
                const SizedBox(height: 22),
                const _SectionTitle('Scans default'),
                _Seg(
                  value: state.scanMode,
                  children: const {
                    'trend': Text('Trend'),
                    'qulla': Text('Qulla'),
                    'edges': Text('Edges'),
                    'setups': Text('Setups'),
                    'fractal': Text('Frac'),
                  },
                  onChanged: state.setScanMode,
                ),
                const SizedBox(height: 8),
                const Text(
                  'Fractal loads /api/fractal/scan (SPEC 25/27 rebuild). HMM is a research label, not edge — SPY only. Finviz is public HTML + cache.',
                  style: TextStyle(color: DeskColors.muted, fontSize: 12, height: 1.35),
                ),
                const SizedBox(height: 22),
                const _SectionTitle('Finviz'),
                Row(
                  children: [
                    const Expanded(
                      child: Text(
                        'Enable Finviz fetch + SQLite cache',
                        style: TextStyle(color: DeskColors.text, fontSize: 13),
                      ),
                    ),
                    CupertinoSwitch(
                      value: state.finvizEnabled,
                      onChanged: state.setFinvizEnabled,
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  'Cache TTL ${state.finvizTtlSec}s. No API keys. Blocks stay empty.',
                  style: const TextStyle(color: DeskColors.muted, fontSize: 12),
                ),
                const SizedBox(height: 8),
                _Seg(
                  value: '${state.finvizTtlSec}',
                  children: const {
                    '900': Text('15m'),
                    '3600': Text('1h'),
                    '14400': Text('4h'),
                    '86400': Text('1d'),
                  },
                  onChanged: (v) => state.setFinvizTtl(int.tryParse(v) ?? 3600),
                ),
                const SizedBox(height: 22),
                const _SectionTitle('Universe'),
                const Text(
                  'Core 50 adds liquid desk names (no Yahoo download). S&P sync registers univ:* archive only — fetch is optional and slow.',
                  style: TextStyle(color: DeskColors.muted, fontSize: 12),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    CupertinoButton.filled(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      onPressed: state.seedingSleeve ? null : state.seedCore50,
                      child: const Text('Seed Core 50', style: TextStyle(fontSize: 13)),
                    ),
                    const SizedBox(width: 8),
                    CupertinoButton(
                      padding: const EdgeInsets.symmetric(horizontal: 12),
                      onPressed: state.seedingUniverse ? null : state.registerSp500,
                      child: const Text('Register S&P', style: TextStyle(fontSize: 13)),
                    ),
                  ],
                ),
                if (state.scannerStatus['running'] == true)
                  const Text(
                    'Bulk archive is running — progress on Scans.',
                    style: TextStyle(color: Color(0xFFEAB308), fontSize: 12),
                  ),
                const SizedBox(height: 22),
                const _SectionTitle('Sleeves'),
                const Text(
                  'One-tap Yahoo ETF proxies. Tags the desk group. Not GDP or a fund pick.',
                  style: TextStyle(color: DeskColors.muted, fontSize: 12),
                ),
                const SizedBox(height: 8),
                for (final sleeve in state.sleeves) ...[
                  _SleeveRow(
                    sleeve: sleeve,
                    busy: state.seedingSleeve,
                    onSeed: () => state.seedSleeve(sleeve.id),
                  ),
                  const SizedBox(height: 8),
                ],
                const SizedBox(height: 16),
                const _SectionTitle('About'),
                Text(
                  'Paper / local only — no live trading. No API keys. '
                  'Qulla tags are momentum / EP-style desk heuristics from our scanner, '
                  'not Kristjan Qullamaggie formulas or claimed returns.\n\n'
                  '${state.fractalStatus.source.isEmpty ? 'Fractal: SPEC 25/27 in-repo estimator.' : state.fractalStatus.source} '
                  'HMM: research label, not edge.',
                  style: const TextStyle(color: DeskColors.muted, fontSize: 13, height: 1.4),
                ),
              ],
            );
          },
        ),
      ),
    );
  }
}

class _SectionTitle extends StatelessWidget {
  const _SectionTitle(this.text);
  final String text;

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 8),
      child: Text(
        text.toUpperCase(),
        style: const TextStyle(
          color: DeskColors.dim,
          fontSize: 11,
          fontWeight: FontWeight.w700,
          letterSpacing: 0.6,
        ),
      ),
    );
  }
}

class _Seg extends StatelessWidget {
  const _Seg({
    required this.value,
    required this.children,
    required this.onChanged,
  });

  final String value;
  final Map<String, Widget> children;
  final ValueChanged<String> onChanged;

  @override
  Widget build(BuildContext context) {
    return CupertinoSlidingSegmentedControl<String>(
      groupValue: children.containsKey(value) ? value : children.keys.first,
      children: {
        for (final e in children.entries)
          e.key: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 6),
            child: DefaultTextStyle.merge(
              style: const TextStyle(fontSize: 12),
              child: e.value,
            ),
          ),
      },
      onValueChanged: (v) {
        if (v != null) onChanged(v);
      },
    );
  }
}

class _ToggleChip extends StatelessWidget {
  const _ToggleChip({required this.label, required this.on, required this.onTap});

  final String label;
  final bool on;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 5),
        decoration: BoxDecoration(
          color: on ? DeskColors.accent.withValues(alpha: 0.2) : DeskColors.card,
          borderRadius: BorderRadius.circular(8),
          border: Border.all(color: on ? DeskColors.accent : DeskColors.border),
        ),
        child: Text(
          label,
          style: TextStyle(
            color: on ? DeskColors.accentBright : DeskColors.muted,
            fontSize: 11,
            fontWeight: FontWeight.w600,
          ),
        ),
      ),
    );
  }
}

class _SleeveRow extends StatelessWidget {
  const _SleeveRow({
    required this.sleeve,
    required this.busy,
    required this.onSeed,
  });

  final dynamic sleeve;
  final bool busy;
  final VoidCallback onSeed;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(10),
      decoration: BoxDecoration(
        color: DeskColors.card,
        borderRadius: BorderRadius.circular(10),
        border: Border.all(color: DeskColors.border),
      ),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  sleeve.label as String,
                  style: const TextStyle(
                    color: DeskColors.text,
                    fontWeight: FontWeight.w600,
                    fontSize: 14,
                  ),
                ),
                Text(
                  '${(sleeve.tickers as List).join(' · ')}',
                  style: const TextStyle(color: DeskColors.muted, fontSize: 11),
                ),
              ],
            ),
          ),
          CupertinoButton(
            padding: const EdgeInsets.symmetric(horizontal: 10),
            onPressed: busy ? null : onSeed,
            child: const Text('Add', style: TextStyle(fontSize: 13)),
          ),
        ],
      ),
    );
  }
}
