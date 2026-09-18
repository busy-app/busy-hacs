# BUSY Bar for Home Assistant

Draft integration of the BUSY Bar into Home Assistant.

Discovery works :P

## What a bar can show and play

Notifications, icons, themes and sounds come from the bar itself - it ships
with a set of pictures, animations, sounds and themes, and nothing has to be
uploaded to use them. Every one of them, with pictures you can actually look
at and sounds you can play, is in
[busylib's stock assets guide](https://busy-app.github.io/busylib-py/guides/stock-assets/).

Which of them a **particular** bar has is a different question - a release
adds some, an owner uploads others - and that one the bar answers itself:

```yaml
actions:
  - action: busy.list_assets
    target:
      device_id: <your bar>
    response_variable: assets
```

Run it from **Developer tools → Actions** and it answers with every icon,
animation, sound, font and theme that bar holds, the firmware's own and the
uploaded ones apart. Those are the names the `icon`, `sound` and `theme`
fields take.

## Icons for the notify action

The **Show a notification** action draws an icon at the left edge. Eight have
short names - `check`, `error`, `info`, `clock`, `hourglass`, `low_battery`,
`start`, `setup` - and the rest are the Draw Tool's set, under exactly the
names the Draw Tool shows, so a picture of any of them is one tap away in the
BUSY app.

Anything else on the bar works too: the dropdown accepts a typed name, and a
name that bar does not have is refused with the list it does have. That
matters because icons are files - an owner can upload their own or delete
what they do not want - so no list written down here is true of every bar.

The Draw Tool icons are 16x16, twice the width of most of the built-in ones.
The layout shifts the text accordingly, which leaves 56 of the panel's 72
pixels for it.

| Draw Tool icons | | | |
| --- | --- | --- | --- |
| `dt_apple_green` | `dt_apple_red` | `dt_apple_yellow` | `dt_available` |
| `dt_basketball` | `dt_book` | `dt_burger` | `dt_chicken` |
| `dt_coctail` | `dt_coffee` | `dt_crescent_moon_1` | `dt_crescent_moon_2` |
| `dt_dialog` | `dt_dialog_no` | `dt_dialog_yes` | `dt_drink_1` |
| `dt_drink_2` | `dt_emoji_angry` | `dt_emoji_awkward` | `dt_emoji_cry` |
| `dt_emoji_dead` | `dt_emoji_evil` | `dt_emoji_expressionless` | `dt_emoji_eyes` |
| `dt_emoji_fatigue` | `dt_emoji_glasses` | `dt_emoji_grinning` | `dt_emoji_happy` |
| `dt_emoji_heart_eyes` | `dt_emoji_laught` | `dt_emoji_melted` | `dt_emoji_panic` |
| `dt_emoji_relief` | `dt_emoji_sad` | `dt_emoji_sleep` | `dt_emoji_surprised` |
| `dt_emoji_sweat_smile` | `dt_emoji_tounge` | `dt_football` | `dt_heart_blue` |
| `dt_heart_green` | `dt_heart_light_blue` | `dt_heart_orange` | `dt_heart_pink` |
| `dt_heart_red` | `dt_heart_violet` | `dt_heart_yellow` | `dt_home` |
| `dt_leaf` | `dt_moon_1` | `dt_moon_2` | `dt_no` |
| `dt_pie` | `dt_pizza` | `dt_pizza_margarita` | `dt_pizza_peperoni` |
| `dt_sparkls_1` | `dt_sparkls_2` | `dt_study` | `dt_tea` |
| `dt_tennis` | `dt_toast` | `dt_tomato` | `dt_unavailable` |
| `dt_work` | `dt_yes` |

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
