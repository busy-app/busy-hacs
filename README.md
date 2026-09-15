# BUSY Bar for Home Assistant

Draft integration of the BUSY Bar into Home Assistant.

Discovery works :P

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
