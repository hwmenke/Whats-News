import 'package:flutter/cupertino.dart';

import '../data/app_state.dart';
import '../data/api_client.dart';
import 'theme.dart';

Future<void> showServerSheet(BuildContext context, WhatsNewsState state) {
  final controller = TextEditingController(text: state.baseUrl);
  return showCupertinoModalPopup<void>(
    context: context,
    builder: (context) {
      return CupertinoActionSheet(
        title: const Text('Local data server'),
        message: Padding(
          padding: const EdgeInsets.only(top: 8),
          child: Column(
            children: [
              const Text(
                'Simulator on this Mac: http://127.0.0.1:8050\n'
                'Physical iPhone: http://<Mac-LAN-IP>:8050 with HOST=0.0.0.0\n'
                'Optional data plane: :8051',
                textAlign: TextAlign.left,
                style: TextStyle(fontSize: 13),
              ),
              const SizedBox(height: 10),
              CupertinoTextField(
                controller: controller,
                placeholder: kDefaultApiBase,
                style: const TextStyle(color: DeskColors.text),
                decoration: BoxDecoration(
                  color: DeskColors.card,
                  borderRadius: BorderRadius.circular(8),
                ),
              ),
            ],
          ),
        ),
        actions: [
          CupertinoActionSheetAction(
            onPressed: () async {
              await state.setBaseUrl(controller.text);
              if (context.mounted) Navigator.pop(context);
              await state.refreshAll();
            },
            child: const Text('Save & reconnect'),
          ),
        ],
        cancelButton: CupertinoActionSheetAction(
          onPressed: () => Navigator.pop(context),
          child: const Text('Cancel'),
        ),
      );
    },
  );
}
