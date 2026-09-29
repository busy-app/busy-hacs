# Brand images

What [home-assistant/brands](https://github.com/home-assistant/brands) needs,
cut from the official BUSY brand kit. Without them Home Assistant draws a
grey placeholder where the integration's icon belongs.

| File | Size | What it is |
| --- | --- | --- |
| `icon.png` / `icon@2x.png` | 256, 512 | The BUSY app icon, as shipped |
| `logo.png` / `logo@2x.png` | 256 tall | The wordmark for light backgrounds |
| `dark_logo.png` / `dark_logo@2x.png` | 256 tall | The wordmark for dark backgrounds |

Nothing here is drawn by hand: the kit says to use the official files only -
never recreate, recolour, stretch, crop, rotate or add effects - so these are
those files scaled, and nothing else. The kit's own pairing is kept: black
wordmark on light, white wordmark on dark.

The one place this departs from the kit is clear space. The kit asks for the
symbol's height around the logo; brands asks for the opposite, "trimmed, so it
contains the minimum amount of empty space on the edges", because Home
Assistant lays out the space itself. The files are therefore untrimmed and
unpadded - exactly the artwork as delivered.

## Submitting them

Brands lives in its own repository and is not installed with the integration:

1. Fork `home-assistant/brands`.
2. Copy this folder's PNGs to `custom_integrations/busy/`.
3. Open a pull request. The domain folder has to be `busy`, matching
   `manifest.json`.

Until that lands, Home Assistant shows a placeholder, which is also what the
`brands` rule of the quality scale is about.
