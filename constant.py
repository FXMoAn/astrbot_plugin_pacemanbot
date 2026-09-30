from pathlib import Path

CURRENT_DIR = Path(__file__).resolve().parent
ASSETS_DIR = CURRENT_DIR / "public"
TEMPLATE_DIR = ASSETS_DIR / "templates"
DEFAULT_TEMPLATE = "pacestats"
CARD_SIZE = (1280, 720)
CARD_TEMPLATES = {
    "pacestats": TEMPLATE_DIR / "pacestats.html",
    "run": TEMPLATE_DIR / "run.html",
}


def get_template_path(template_name: str) -> Path:
    return CARD_TEMPLATES.get(template_name, CARD_TEMPLATES[DEFAULT_TEMPLATE])
