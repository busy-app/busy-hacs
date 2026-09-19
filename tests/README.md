# Tests

```bash
uv run --group test pytest
```

A real Home Assistant, the real integration, and a fake bar at the seam
where the library would reach for hardware. That seam is deliberate:
what is worth testing here is what a bar cannot be asked to do on demand
- move to another address mid-session, have its HTTP API switched off,
be two bars - and those are exactly the cases that cost hours to find by
hand.

| File | What it holds to |
| --- | --- |
| `test_config_flow.py` | Adding a bar: discovery, the address it is added at, the picker with two bars, a bar already added, a bar with its HTTP API off |
| `test_setup.py` | Starting up: a remembered address, a bar that moved, a bar that is not there, two bars kept apart |
| `test_sessions.py` | Which card a session runs on, and that a quick one touches neither of the bar's own |
| `test_firmware_update.py` | Which of the firmware's install phases mean "installing" |
| `test_integration_shape.py` | The things that shipped broken at least once: a platform building a class that was deleted, an entity with no name, an action offered but not described |

## What still needs hardware

Two things cannot be faked honestly, and both are quick to do by hand:

- **Turning the HTTP API off.** The setting is on the bar itself, and a
  bar with it off is reachable only over its USB network, so this needs a
  machine plugged into that bar - `http://10.0.4.20` by default. The
  fake covers what Home Assistant then sees (announced, unreachable, and
  aborted by name rather than asked for a password); what it cannot cover
  is that the firmware still announces itself in that state.
- **A real DHCP lease change.** Faked here by moving the bar between
  addresses and re-announcing it. Worth doing once for real against a
  router that can be made to hand out a different address.
