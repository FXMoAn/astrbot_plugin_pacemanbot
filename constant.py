import os
from typing import Dict

CURRENT_DIR = os.path.dirname(__file__)
ASSETS_DIR = os.path.join(CURRENT_DIR, "public")
TEMPLATE_DIR = os.path.join(ASSETS_DIR, "templates")

CARD_TEMPLATES: Dict[str, dict] = {
    "pacestats": {
        "name": "pacestats",
        "path": os.path.join(TEMPLATE_DIR, "pacestats.html"),
        "file": "pacestats.html",
    }
}

DEFAULT_TEMPLATE = "pacestats"

def get_template_path(type: str) -> str:
    template = CARD_TEMPLATES.get(type, CARD_TEMPLATES[DEFAULT_TEMPLATE])
    return template["path"]

MAX_ATTEMPTS = 3
RETRY_DELAY = 2
RECENT_DYNAMIC_CACHE = 4