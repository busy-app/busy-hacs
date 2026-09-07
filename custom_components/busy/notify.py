"""The templated notify action for the BUSY Bar integration.

One action rather than one per layout. Which template is used follows from
the fields that were filled in - a second line, an icon or a background
colour each change the drawing - so the caller never supplies coordinates.
That was a deliberate decision: exposing x/y meant every automation author
redoing the same pixel arithmetic, and the panel is only 72x16, where a
wrong offset silently clips the text.
"""

from __future__ import annotations

import logging
from typing import Any

from .const import (
    APPLICATION_NAME,
    FRONT_HEIGHT,
    FRONT_WIDTH,
    ICON_TEXT_GAP,
    ONE_LINE_Y,
    SCROLL_RATE,
    SCROLL_THRESHOLD_CHARS,
    STOCK_ICONS,
    TWO_LINE_Y,
)

_LOGGER = logging.getLogger(__name__)

# The element id doubles as z-order on the device: higher sits on top. The
# background has to be under everything, so foreground ids start well above
# it and leave room to add elements later without renumbering.
_BACKGROUND_ID = "0"
_ICON_ID = "10"
_LINE_1_ID = "11"
_LINE_2_ID = "12"


def _rgb(colour: list[int] | tuple[int, int, int] | None) -> str | None:
    """
    Turn an HA `color_rgb` triple into the device's #RRGGBBAA form.
    """
    if colour is None:
        return None
    red, green, blue = colour
    return f"#{red:02X}{green:02X}{blue:02X}FF"


def _icon(name: str | None) -> tuple[str, int] | None:
    """
    Resolve an icon name to its (stock_path, width), or None for no icon.
    """
    if not name or name == "none":
        return None
    resolved = STOCK_ICONS.get(name)
    if resolved is None:
        # Unknown names are dropped rather than sent on: the device answers
        # 400 "Failed to decode image" for a path it cannot resolve, which
        # would fail the whole notification over a cosmetic detail.
        _LOGGER.warning("unknown icon %r, drawing without one", name)
    return resolved


def _scroll(text: str, available: int) -> dict[str, Any]:
    """
    Scroll a line only when it cannot fit the width left for it.

    Scrolling is the text element's own feature, so this just decides when to
    switch it on. The threshold is a character count rather than a measured
    width: glyph widths differ per font and the device does not report them,
    so a short line staying still matters more than being exact at the edge.
    """
    if available <= 0:
        return {}
    budget = max(1, SCROLL_THRESHOLD_CHARS * available // FRONT_WIDTH)
    if len(text) <= budget:
        return {}
    return {"width": available, "scroll_rate": SCROLL_RATE}


def _text(
    element_id: str,
    text: str,
    *,
    font: str,
    colour: str | None,
    x: int,
    y: int,
    align: str,
    duration: int,
) -> dict[str, Any]:
    """
    Build one text element, scrolling it if the remaining width is too small.
    """
    element: dict[str, Any] = {
        "id": element_id,
        "type": "text",
        "display": "front",
        "text": text,
        "font": font,
        "align": align,
        "x": x,
        "y": y,
        "timeout": duration,
        **_scroll(text, FRONT_WIDTH - x),
    }
    if colour is not None:
        element["color"] = colour
    return element


def build_elements(
    *,
    line_1: str,
    line_2: str | None = None,
    icon: str | None = None,
    font: str,
    line_1_color: list[int] | None = None,
    line_2_color: list[int] | None = None,
    background_color: list[int] | None = None,
    duration: int,
    priority: int,
) -> dict[str, Any]:
    """
    Build the draw payload for whichever template the fields imply.

    Four layouts, chosen here and not by the caller: one line, one line with
    an icon, two lines, two lines with an icon. An icon shifts the text right
    by its own width, which is why the width is carried alongside the path -
    the shipped icons are 5, 8 and 11px wide, so a fixed offset would either
    overlap or leave a gap.
    """
    resolved_icon = _icon(icon)
    text_x = resolved_icon[1] + ICON_TEXT_GAP if resolved_icon else 2

    elements: list[dict[str, Any]] = []

    if background_color is not None:
        # Firmware 27.x draws a real filled rectangle. The prototype had to
        # emulate this by tiling a dense glyph across the panel because the
        # draw API had no fill primitive at the time; verified on 27.7.0 that
        # a solid rectangle now renders, so the tiling is gone.
        elements.append(
            {
                "id": _BACKGROUND_ID,
                "type": "rectangle",
                "display": "front",
                "x": 0,
                "y": 0,
                "width": FRONT_WIDTH,
                "height": FRONT_HEIGHT,
                "fill": "solid",
                "fill_colors": [_rgb(background_color)],
                "border_width": 0,
                "timeout": duration,
            }
        )

    if resolved_icon is not None:
        elements.append(
            {
                "id": _ICON_ID,
                "type": "image",
                "display": "front",
                "stock_path": resolved_icon[0],
                "align": "mid_left",
                "x": 0,
                "y": FRONT_HEIGHT // 2,
                "timeout": duration,
            }
        )

    if line_2:
        top_y, bottom_y = TWO_LINE_Y[font]
        elements.append(
            _text(
                _LINE_1_ID,
                line_1,
                font=font,
                colour=_rgb(line_1_color),
                x=text_x,
                y=top_y,
                align="top_left",
                duration=duration,
            )
        )
        elements.append(
            _text(
                _LINE_2_ID,
                line_2,
                font=font,
                colour=_rgb(line_2_color),
                x=text_x,
                y=bottom_y,
                align="bottom_left",
                duration=duration,
            )
        )
    else:
        elements.append(
            _text(
                _LINE_1_ID,
                line_1,
                font=font,
                colour=_rgb(line_1_color),
                x=text_x,
                y=ONE_LINE_Y[font],
                align="mid_left",
                duration=duration,
            )
        )

    return {
        "application_name": APPLICATION_NAME,
        "priority": priority,
        "elements": elements,
    }
