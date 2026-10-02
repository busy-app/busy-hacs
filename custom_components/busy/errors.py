"""One place that turns what the library raises into what Home Assistant shows."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from busylib.exceptions import BusyBarError, BusyBarFeatureUnavailableError
from busylib.features import timer
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError

from .const import DOMAIN


def translate(
    err: Exception,
    *,
    failed: str = "timer_failed",
    invalid: str = "invalid_timer_request",
    bar: str | None = None,
) -> HomeAssistantError:
    """
    The error to raise for one the library raised.

    A mistake in the automation (an unknown theme, a length the bar will
    not run, a pause with nothing running) is a validation error, because
    retrying will not help; anything else the bar refused is `failed`, the
    key of the action's own message. `bar` says which bar answered when a
    target reached several.
    """
    detail = f"{bar}: {err}" if bar else str(err)
    placeholders = {"error": detail}
    validation = True
    if isinstance(err, timer.UnknownThemeError):
        key = "unknown_theme"
        placeholders = {"theme": err.theme, "available": ", ".join(err.available)}
    elif isinstance(err, timer.TimerNotRunningError):
        key = "timer_not_running"
    elif isinstance(err, timer.PhaseTooShortError):
        key = "phase_too_short"
    elif isinstance(err, BusyBarFeatureUnavailableError):
        # The fix is a firmware update, not a retry.
        key = "feature_needs_newer_firmware"
        placeholders = {
            "feature": err.feature,
            "required_version": err.required_version,
            "device_version": str(err.device_version),
        }
    elif isinstance(err, ValueError):
        key = invalid
    else:
        key, validation = failed, False

    error = ServiceValidationError if validation else HomeAssistantError
    return error(
        translation_domain=DOMAIN,
        translation_key=key,
        translation_placeholders=placeholders,
    )


@contextmanager
def reporting(failed: str, **kwargs: str) -> Iterator[None]:
    """
    Raise whatever the body's library calls raise as a translated error.
    """
    try:
        yield
    except (BusyBarError, ValueError) as err:
        raise translate(err, failed=failed, **kwargs) from err
