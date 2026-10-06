# Brand images

The images Home Assistant shows for the integration; the logos are cut from
the official BUSY brand kit. Without them Home Assistant draws a grey
placeholder where the integration's icon belongs.

| File | Size | What it is |
| --- | --- | --- |
| `icon.png` / `icon@2x.png` | 256, 512 | The BUSY icon |
| `logo.png` / `logo@2x.png` | 256 tall | The wordmark for light backgrounds |
| `dark_logo.png` / `dark_logo@2x.png` | 256 tall | The wordmark for dark backgrounds |

Nothing in the logos is drawn by hand: the kit says to use the official files only -
never recreate, recolour, stretch, crop, rotate or add effects - so these are
those files scaled, and nothing else. The kit's own pairing is kept: black
wordmark on light, white wordmark on dark.

The one place this departs from the kit is clear space. The kit asks for the
symbol's height around the logo; brands asks for the opposite, "trimmed, so it
contains the minimum amount of empty space on the edges", because Home
Assistant lays out the space itself. The files are therefore untrimmed and
unpadded - exactly the artwork as delivered.

## Where they live

Home Assistant 2026.3 and later read brand images from the integration's own
`brand/` folder, ahead of the brands CDN, and home-assistant/brands no longer
takes new custom integrations. Older versions show a placeholder.
