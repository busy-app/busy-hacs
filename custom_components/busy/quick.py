"""Quick sessions: kept in Home Assistant, run on neither of the bar's cards."""

from __future__ import annotations

from dataclasses import dataclass, field

from busylib import AsyncBusyBar
from busylib.features import timer

# The card a quick session names. A snapshot has to name one, and this is
# deliberately neither of the bar's two: the bar holds a card per switch
# position, the BUSY app holds more, and naming another one means a quick
# session cannot disturb either position - not even by name. The app shows
# the session under that card, which is how a person sees where it came from.
QUICK_CARD_ID = "00000000-0000-0000-0000-000000000003"


@dataclass
class QuickSession:
    """
    What the quick switches run.

    Not on the bar: writing any of it there would change one of the two
    cards, which is the thing quick sessions exist to avoid. It lives here,
    is shown as themes and numbers, and is read when a session starts - so
    an automation can set one and start the other.
    """

    simple_minutes: int = 45
    work_minutes: int = 25
    rest_minutes: int = 5
    cycles: int = 4
    themes: dict[str, str] = field(
        default_factory=lambda: {
            "infinite": "busy",
            "simple": "busy",
            "interval": "busy",
        }
    )


async def check_theme(client: AsyncBusyBar, theme: str | None) -> None:
    """
    Refuse a theme this bar does not have.

    The bar does not: a session naming a theme it has no assets for starts
    anyway, shows the default, and reports the missing one as the theme it
    is running. `busy` is always there - it is the firmware's own and has no
    directory - so it is allowed whether or not a card names it.
    """
    if theme is None or theme == timer.DEFAULT_THEME:
        return
    known = await timer.themes(client)
    if theme not in known:
        raise timer.UnknownThemeError(theme, sorted({*known, timer.DEFAULT_THEME}))


async def start(
    client: AsyncBusyBar,
    quick: QuickSession,
    kind: timer.TimerKind,
    *,
    duration: int | None = None,
    rest: int | None = None,
    cycles: int | None = None,
    theme: str | None = None,
) -> None:
    """
    Start a quick session of one kind.

    It carries its own settings, so nothing is written to a card, and it
    names a card outside both switch positions. Anything the caller leaves
    out comes from `quick`, the settings shown as entities. Lengths are in
    minutes, as a person writes them; the bar wants milliseconds.
    """
    interval = kind == "interval"
    if kind != "infinite" and duration is None:
        duration = quick.work_minutes if interval else quick.simple_minutes
    if interval and rest is None:
        rest = quick.rest_minutes
    if interval and cycles is None:
        cycles = quick.cycles

    def ms(minutes: int | None) -> int | None:
        return None if minutes is None else minutes * 60_000

    theme = theme or quick.themes.get(kind)
    await check_theme(client, theme)
    await timer.start(
        client,
        card_id=QUICK_CARD_ID,
        kind=kind,
        duration_ms=ms(duration),
        rest_ms=ms(rest),
        cycles=cycles,
        theme=theme,
    )
