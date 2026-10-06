"""
What the library raises, and what a person reads: a mistake in the
automation is a validation error, because retrying will not help, and
anything else the bar refused is a failure of the action.
"""

from __future__ import annotations

from busylib.exceptions import BusyBarError, BusyBarFeatureUnavailableError
from busylib.features import timer
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import pytest

from custom_components.busy.errors import translate


@pytest.mark.parametrize(
    ("error", "key", "validation"),
    [
        (timer.UnknownThemeError("x", ["a", "b"]), "unknown_theme", True),
        (timer.TimerNotRunningError("none"), "timer_not_running", True),
        (timer.PhaseTooShortError("work", 1000), "phase_too_short", True),
        (
            BusyBarFeatureUnavailableError(feature="f", required_version="1"),
            "feature_needs_newer_firmware",
            True,
        ),
        (ValueError("bad length"), "invalid_timer_request", True),
        (BusyBarError("refused"), "timer_failed", False),
    ],
)
def test_each_error_lands_on_its_own_message(error, key, validation) -> None:
    translated = translate(error)

    assert translated.translation_key == key
    assert isinstance(translated, ServiceValidationError) is validation
    assert isinstance(translated, HomeAssistantError)


def test_the_message_keys_are_the_callers_to_choose() -> None:
    translated = translate(
        ValueError("no"), failed="notify_failed", invalid="invalid_notification"
    )
    assert translated.translation_key == "invalid_notification"
    assert translate(BusyBarError("no"), failed="notify_failed").translation_key == (
        "notify_failed"
    )


def test_an_error_says_which_bar_answered() -> None:
    translated = translate(BusyBarError("refused"), bar="Desk")

    assert translated.translation_placeholders == {"error": "Desk: refused"}
