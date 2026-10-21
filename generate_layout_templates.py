"""generate_layout_templates.py - build the layout template library.

Creates, in `layout_templates/`:
  * previews/                 one PNG per template, rendered on the ComfyUI background
  * presentation_layout_templates.pptx   specimen deck (editable native shapes)
  * layout_template_catalogue.md         the catalogue (64 templates + why each was added)
  * layout_template_gallery.png          a contact sheet of every template

Usage:
    python generate_layout_templates.py                 # use the newest ComfyUI background
    python generate_layout_templates.py --background path/to/slide_1_0.png
    python generate_layout_templates.py --force         # re-render even if cached
    python generate_layout_templates.py --light         # flat light theme (no background)
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PIL import Image

from layout_catalogue import TEMPLATES
from layout_engine import DARK_THEME, LIGHT_THEME, render_to_png
from layout_templates import (CATALOG_FILE, PREVIEW_DIR, TEMPLATE_DECK, build_template_deck,
                              build_template_previews, find_background, preview_path_for,
                              write_catalogue_markdown)


def contact_sheet(out_path, cols=4, tile=(400, 225)):
    """One image showing every template - handy for a quick visual review."""
    paths = [preview_path_for(t) for t in TEMPLATES]
    paths = [p for p in paths if os.path.exists(p)]
    if not paths:
        return None
    tw, th = tile
    rows = (len(paths) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * th), (8, 10, 16))
    for i, path in enumerate(paths):
        try:
            with Image.open(path) as im:
                im = im.convert("RGB").resize((tw, th), Image.LANCZOS)
        except Exception:
            continue
        sheet.paste(im, ((i % cols) * tw, (i // cols) * th))
    os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
    sheet.save(out_path, quality=92)
    return out_path


def main():
    parser = argparse.ArgumentParser(description="Build the layout template library.")
    parser.add_argument("--background", default=None, help="ComfyUI background image to use")
    parser.add_argument("--force", action="store_true", help="re-render previews even if cached")
    parser.add_argument("--light", action="store_true", help="flat light theme, no background")
    parser.add_argument("--dpi", type=int, default=110, help="preview resolution")
    args = parser.parse_args()

    background = None if args.light else find_background(args.background)
    theme = LIGHT_THEME if args.light else DARK_THEME
    print(f"Background: {background or '(none - flat theme)'}")

    print("Rendering previews...")
    items = build_template_previews(background=background, force=args.force, dpi=args.dpi)
    print(f"  {len(items)} templates -> {PREVIEW_DIR}")

    print("Building the specimen deck...")
    deck = build_template_deck(background=background)
    print(f"  {deck}")

    print("Writing the catalogue...")
    md = write_catalogue_markdown()
    print(f"  {md}")

    sheet = contact_sheet(os.path.join(os.path.dirname(TEMPLATE_DECK), "layout_template_gallery.png"))
    if sheet:
        print(f"  {sheet}")

    print(f"\nDone: {len(TEMPLATES)} layout templates are ready.")


if __name__ == "__main__":
    main()
