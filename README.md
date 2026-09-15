# BUSY Bar for Home Assistant

Draft integration of the BUSY Bar into Home Assistant.

Discovery works :P

## Volume mute, and why it is not the volume slider set to zero

Setting the volume to zero silences the bar and forgets how loud it was.
Mute remembers: turn it on and the bar goes quiet, turn it off and the
volume it had comes back. That is the difference worth an entity - an
automation can silence the bar for a call, or for the night, without
having to read the volume first and put it back afterwards:

```yaml
actions:
  - action: switch.turn_on
    target:
      entity_id: switch.busy_bar_volume_mute
  # ... the meeting happens ...
  - action: switch.turn_off
    target:
      entity_id: switch.busy_bar_volume_mute
```

The firmware has no mute of its own, so this is volume zero underneath.
Two consequences follow from that and are worth knowing: the remembered
level lives in Home Assistant, so it does not survive a restart, and a bar
that was already silent when Home Assistant started has nothing to
restore - unmuting then picks a middle volume rather than guessing loud.
