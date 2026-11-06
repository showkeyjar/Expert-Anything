"""PyInstaller runtime hook: redirect the app's data dir when frozen.

When built with PyInstaller, source files live in ``sys._MEIPASS`` and are
read-only. The app, however, writes to its data dir (learner.json, imported
assets, the index/cache DBs). So we point ``EXPERTANYTHING_DATA_DIR`` at a
writable folder next to the executable and seed it from the bundled (read-only)
data on first run.
"""
import os
import shutil
import sys

if getattr(sys, "frozen", False) and not os.environ.get("EXPERTANYTHING_DATA_DIR"):
    exe_dir = os.path.dirname(sys.executable)
    user_data = os.path.join(exe_dir, "data")
    os.makedirs(user_data, exist_ok=True)

    seed = os.path.join(getattr(sys, "_MEIPASS", ""), "data")
    if os.path.isdir(seed):
        for name in os.listdir(seed):
            src = os.path.join(seed, name)
            dst = os.path.join(user_data, name)
            if os.path.exists(dst):
                continue
            try:
                if os.path.isdir(src):
                    shutil.copytree(src, dst)
                else:
                    shutil.copy2(src, dst)
            except OSError:
                pass

    os.environ["EXPERTANYTHING_DATA_DIR"] = user_data
