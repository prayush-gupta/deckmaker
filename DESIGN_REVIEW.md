# Layout design review (64 original layouts + 4 added)

How it was checked: every layout was rendered with its sample content, with text lengthened
x1.6, with the maximum number of items, and with both together; text boxes were checked for
overflow, collisions and margin violations. The exported .pptx was then opened in LibreOffice
and inspected with python-pptx.

## Bugs found and fixed
| # | Finding | Fix |
|---|---------|-----|
| 1 | **All transparency was dropped in the exported .pptx** (`_alpha` searched for a child of the colour element, found nothing and returned). The dark scrim therefore hid the background artwork completely and cards/overlays were solid, while the PNG preview showed them translucent, so preview and PowerPoint disagreed. | `_alpha` now sets the alpha on the colour element itself. |
| 2 | Timeline labels started left of the safe margin (x = 0.42 in) and ran past the right margin. | Labels are clamped inside LEFT..RIGHT. |
| 3 | Bar chart (L18) had no value labels or baseline, so readers had to guess the numbers. | Value labels above bars + a zero baseline. |
| 4 | Light theme with artwork had no scrim, so dark text sat on busy art. | Pale veil over the artwork in light theme. |

## Design considerations added
- **Minimum type size 10 pt** (text was drawn at 7.2 to 9.5 pt: source footer, eyebrow labels, axis labels).
- **Adaptive scrim**: the theme scrim is the floor; brighter artwork gets a stronger scrim, text-dense slides slightly more.
- **Real slide titles**: slides use the "Title Only" layout and the title is written into the title placeholder (outline view, slide navigator, screen readers, accessibility checker). The placeholder sits above the artwork but stays first in reading order.
- **Alt text**: background artwork is named and described as decorative.
- **Speaker notes**: the full source text for each slide (including research evidence and sources) is stored in the notes, so the slide can stay short without losing the detail. Notes are never flattened back into the visible text box.
- **Per-field length caps** on LLM output (headings/labels/figures 48 chars, title 80, headline-type fields 160, running text 220), cut at a word boundary with an ellipsis.
- **Status is never colour only** in the new Action Plan layout (text label inside the pill).

## Layouts added
| ID | Name | Why it was missing |
|----|------|--------------------|
| L65 | Executive Summary | answer first: conclusion + headline numbers + the ask on one slide |
| L66 | Venn / Overlap | no set-overlap framework existed |
| L67 | Line / Trend Chart | only time-series visual was a bar chart; has a zero baseline, gridlines, axis values, labelled start/peak/end |
| L68 | Action Plan / Next Steps | owner + date + status; "next steps" used to map to the closing slide L14 |

The heuristic fallback now routes "executive summary", "action plan / next steps", "venn / overlap" and "trend / over time" to the new layouts.

## Known remaining items (not changed)
- Font is hard-coded to Segoe UI. It is fine on Windows; on Mac/Linux PowerPoint substitutes a different font and wrapping differs slightly. A `DECK_FONT` setting would fix this.
- The PNG preview measures text with the font installed on the machine, PowerPoint wraps with its own engine, so a slide that is within 5% of overflowing can differ. The length caps reduce this; a shrink-to-fit pass would remove it.
- Heatmap, risk matrix, SWOT and status colours still rely partly on colour; each has text labels, but a pattern or icon would help colour-blind readers.
- Charts are drawn as shapes, not native PowerPoint charts, so the data cannot be edited through "Edit Data".
- Several layouts leave the lower third empty with low content (e.g. L02 bullets, L65); vertical centring would balance them.
