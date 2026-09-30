"""Load the plugin against real AstrBot APIs with an isolated runtime directory."""

import os
import sys
import tempfile
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[1]
os.environ.setdefault("ASTRBOT_ROOT", tempfile.mkdtemp(prefix="pacemanbot-test-"))
sys.path.insert(0, str(PLUGIN_DIR.parents[2]))
package = types.ModuleType("pacemanbot_test")
package.__path__ = [str(PLUGIN_DIR)]
sys.modules.setdefault("pacemanbot_test", package)
