"""Real flet run to verify FilePicker (a Service) gets mounted + registered.

We run an actual flet desktop session, build the app, and assert that the
FilePicker ended up in page.services AND in the page's service registry
(page._services._services). That registration is exactly what makes
pick_files() NOT time out with "Timeout waiting for invoke method listener".

The window is closed programmatically right after the check so the test exits
cleanly (a short timeout also guards against a hung window).
"""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import flet as ft
from expert_anything.ui.app import ExpertApp


def main(page: ft.Page):
    app = ExpertApp(page)
    fp = app.file_picker

    in_services_list = fp in page.services
    in_registry = fp in page._services._services
    has_id = fp._i is not None

    print("CHECK in page.services:", in_services_list, flush=True)
    print("CHECK in page._services registry:", in_registry, flush=True)
    print("CHECK assigned control id (_i):", has_id, flush=True)

    ok = in_services_list and in_registry and has_id
    print("PICKER_MOUNT_OK" if ok else "PICKER_MOUNT_FAIL", flush=True)

    # Close the window so the test exits (best-effort across flet versions).
    try:
        if hasattr(page, "close"):
            page.close()
        elif hasattr(page.window, "close"):
            page.window.close()
    except Exception:
        pass


if __name__ == "__main__":
    ft.run(main)
