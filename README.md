# BUSY Bar

The [BUSY Bar](https://busy.app) is a desk device with a 72x16 LED panel on
each side, a five-position switch, three buttons and a wheel. This
integration talks to it over your own network, through the bar's HTTP API.
There is no cloud account and nothing leaves the house.

## Use cases

- Show what you are doing to the room: start a focus session from an
  automation, or write "ON AIR" across the back panel while the camera is on.
- Notify without a screen: laundry finished, doorbell pressed, the build
  broke - an icon, two lines and a sound, gone after a few seconds.
- Drive automations from the bar: its buttons, wheel and switch are entities,
  so moving the switch to CUSTOM can mute the speakers and dim the lights.
- Watch the panel from anywhere: the bar's display is a camera entity.

## Prerequisites

The bar must be on the same network as Home Assistant, set up through the
BUSY app, and its HTTP API has to be on.

The API switch is on the bar itself, under **SETTINGS > Wi-Fi**, where its
access key is also shown. A bar announces itself on the network whether the
API is on or off, so one that appears in Home Assistant and then refuses to
be added is almost always a bar with the API still off.

## Installation

The integration is not part of Home Assistant and is installed through
[HACS](https://hacs.xyz) as a custom repository:

1. **HACS** > the three-dot menu > **Custom repositories**.
2. Add `https://github.com/busy-app/busy-hacs`, category **Integration**.
3. Download **BUSY Bar**, then restart Home Assistant.

A bar on the network is then found by itself: **Settings > Devices &
services** shows it under **Discovered**. A bar that is not found can be
added with **Add integration > BUSY Bar**.

## Configuration

Adding a bar asks for one thing, and only when the bar wants it:

- **Wi-Fi access key** - the key shown on the bar under **SETTINGS > Wi-Fi**.
  Home Assistant exchanges it once for a token of its own, which is what it
  uses from then on.

The address is not asked for. The bar is found by mDNS, and a bar that moves
to another address - a new DHCP lease, a move between Wi-Fi and USB - is
followed without being reconfigured.

## Supported functionality

### Entities

| Platform | Entities |
| --- | --- |
| Camera | The front panel, live |
| Select | Switch position, and a theme for each kind of quick session |
| Switch | BUSY and CUSTOM sessions, the three quick sessions, pause, mute, automatic brightness |
| Sensor | Session type, phase, when the phase ends, theme, battery, Wi-Fi network and signal, IP address, Bluetooth, time zone, API version, uptime, USB voltage |
| Binary sensor | Charging, automatic updates, session running |
| Number | Brightness, volume, and the lengths a quick session uses |
| Button | OK, back, start, the wheel both ways, skip to the next phase |
| Event | Each button and the wheel, as they are pressed on the bar |
| Update | The bar's firmware, with progress while it installs |

### Actions

| Action | What it does |
| --- | --- |
| `busy.notify` | Two lines, an icon, a sound and colours, for a few seconds |
| `busy.draw` | One piece of text placed exactly, on either display |
| `busy.clear` | Remove what this integration drew |
| `busy.start_busy`, `busy.start_custom` | Start what the bar's own cards describe |
| `busy.start_quick_infinite`, `busy.start_quick_simple`, `busy.start_quick_interval` | Start a session with settings given here, leaving both cards alone |
| `busy.pause_session`, `busy.resume_session`, `busy.stop_session`, `busy.next_phase` | Steer a running session |
| `busy.set_theme` | Change how the bar looks, for this session or for a card |
| `busy.play_sound` | Play any sound the bar has |
| `busy.list_assets` | Answer with every icon, animation, sound, font and theme this bar holds |
| `busy.upload_asset` | Put a picture or sound of your own on the bar |

A notification:

```yaml
actions:
  - action: busy.notify
    target:
      entity_id: camera.busy_bar_screen
    data:
      line_1: Laundry
      line_2: is done
      line_1_font: bold
      line_2_font: tiny
      icon: check
      sound: event
      duration: 15
```

Something written across the back panel until an automation takes it down:

```yaml
actions:
  - action: busy.draw
    target:
      entity_id: camera.busy_bar_screen
    data:
      text: ON AIR
      display: back
      font: bold
      color: [255, 0, 0]
      align: center
      duration: 0
```

### Icons, sounds and themes

These are files on the bar, so no list written down here is true of every
bar: a firmware release adds some, and an owner can upload or delete others.
`busy.list_assets` answers for the bar in front of you, and the whole shipped
set is pictured in
[busylib's stock assets guide](https://busy-app.github.io/busylib-py/guides/stock-assets/).

Eight icons have short names - `check`, `error`, `info`, `clock`,
`hourglass`, `low_battery`, `start`, `setup`. The rest are the Draw Tool's
set, under the names the Draw Tool shows, so a picture of any of them is one
tap away in the BUSY app. Those are 16 pixels wide against the built-in 8,
which leaves 56 of the panel's 72 for the text beside them.

A file you uploaded yourself wins its name over a built-in one. A file
another application uploaded is named with its folder - `draw_tool/logo` -
and is copied into Home Assistant's own folder the first time it is used,
because the bar resolves a name inside the folder of whichever application
is drawing.

### Dashboard card

The integration ships a card with the panel and every control on it. Add it
with **Add card > Custom: BUSY Bar**, or in YAML:

```yaml
type: custom:busy-bar-card
device_id: <your bar>
```

## Data updates

The bar pushes. Sessions, button presses, the switch and the panel's frames
arrive on a state stream the integration keeps open, so what a person does on
the bar shows up at once. A poll every 30 seconds covers the few settings
that are not on that stream, and drops to every 5 seconds while firmware is
installing.

## Known limitations

- **A running session owns the screen.** While a timer runs, the firmware
  refuses every drawing whatever priority it asks for, so notifications
  cannot be shown until the session ends.
- **The switch reports only when it moves.** Nothing answers "where is it
  now", so the switch position reads as unknown until the first time somebody
  moves it. The last known position is remembered across restarts.
- **Text is drawn in the bar's own bitmap fonts.** Cyrillic is there in every
  font except `tiny`; emoji are dropped, since a colour emoji has no meaning
  in a one-bit font. Use an icon instead.
- **Mute is volume zero underneath**, because the firmware has no mute of its
  own. The level to come back to is remembered by Home Assistant rather than
  by the bar, so it does not survive a restart, and unmuting a bar that was
  already silent at startup picks a middle volume rather than guessing.

## Troubleshooting

### The bar is found but cannot be added

Its HTTP API is off. A bar announces itself either way, which is why it
appears and then fails. Turn the API on under **SETTINGS > Wi-Fi** on the bar
and add it again.

### The bar is not found at all

It is on another network or another subnet - a guest Wi-Fi, or a Home
Assistant in a container with its own network. Check that
`http://<the bar's address>/api/status` answers from the machine running
Home Assistant, and add the bar by address if mDNS does not reach it.

### A notification does not appear

Either a session is running, which refuses every drawing, or another
application is holding the screen. The error says which. For the second case,
**Show it over other drawings** puts the notification above it.

## Removing the integration

This integration follows standard integration removal. Deleting it leaves two
things on the bar, which are harmless and can be removed from the bar itself:

- the access token Home Assistant was given, which stays until it is revoked
  on the bar;
- anything uploaded with `busy.upload_asset`, which stays in the bar's
  storage under `home_assistant`.
