"""Rebuild the bundled UI font; fontTools is a development dependency only."""

import argparse
import re
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

FONT_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = FONT_DIR.parents[1]
UI_SOURCES = (
    PLUGIN_DIR / "paceman.py",
    PLUGIN_DIR / "public" / "templates" / "pacestats.html",
    PLUGIN_DIR / "public" / "templates" / "run.html",
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("upstream_font", type=Path)
    args = parser.parse_args()
    text = "".join(source.read_text(encoding="utf-8") for source in UI_SOURCES)
    characters = set(re.findall(r"[\u3400-\u9fff]", text))
    characters.update(chr(codepoint) for codepoint in range(32, 127))
    characters.update("—·…，。：（）％")
    font = TTFont(args.upstream_font, recalcTimestamp=False)
    missing = {ord(character) for character in characters} - set(font.getBestCmap())
    if missing:
        raise ValueError(f"The source font lacks codepoints: {sorted(missing)}")
    options = subset.Options()
    options.name_IDs = ["*"]
    options.name_languages = ["*"]
    options.hinting = False
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes={ord(character) for character in characters})
    subsetter.subset(font)
    names = {
        1: "PaceManUIChinese",
        2: "Regular",
        3: "PaceManUIChinese-Regular-1.0",
        4: "PaceManUIChinese Regular",
        6: "PaceManUIChinese-Regular",
        16: "PaceManUIChinese",
        17: "Regular",
    }
    for record in font["name"].names:
        if record.nameID in names:
            record.string = names[record.nameID].encode(record.getEncoding())
    if "CFF " in font:
        cff = font["CFF "].cff
        cff.fontNames = [names[6]]
        cff.topDictIndex[0].FullName = names[4]
        cff.topDictIndex[0].FamilyName = names[1]
    output = FONT_DIR / "PaceManUIChinese.otf"
    font.save(output)
    print(
        f"Wrote {output.name}: {len(characters)} codepoints, {output.stat().st_size} bytes"
    )


if __name__ == "__main__":
    main()
