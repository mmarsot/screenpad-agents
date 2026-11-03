# README assets

Images the root [README](../../README.md) shows. The banner comes in a light and a dark version, picked by a `<picture>` element, since GitHub strips CSS from READMEs. The README's screenshots are the app's own, in [`docs/images/`](../images/); [Development](../development.md#the-screenshots) says how they are made.

| File | What it is | How to remake it |
|---|---|---|
| `banner-light.png`, `banner-dark.png` | The header banner | Render [`banner.html`](banner.html) (`?theme=light` and `?theme=dark`) at 1280×320 with a transparent background, for example `google-chrome --headless=new --hide-scrollbars --window-size=1280,320 --default-background-color=00000000 --screenshot=banner-dark.png "file://$PWD/banner.html?theme=dark"`. It uses the Ubuntu Sans font that Ubuntu installs, and loads nothing from the network. |

The banner is a sibling of [screenpad-linux's](https://github.com/mmarsot/screenpad-linux/tree/main/docs/assets): the same laptop deck from above, with the ScreenPad showing the apps page on the Agents page, as in [`agents-page.png`](../images/agents-page.png). The bar holds push to talk, the `agents` tile (the helm, 1 blocked) and Captain's Call's page item (the cap, 2 waiting), two empty spots, the page button and the grip; below it are Captain's Call, one blocked agent, two working and one idle. The helm and the cap are copied from [`icons/`](../../icons/).

The colours are screenpad-linux's "night deck": ink `#0E1726` and slate `#1E293B`, teal `#2DD4BF` (text-safe on light `#0F766E`), amber `#FBBF24` (text-safe `#B45309`), mist `#EEF6F5`, line `#D5E6E3`, soft ink `#475569`. The panel uses the touch bar's own tones: amber `#E5A50A` for blocked, green `#26A269` for working, grey `#3A3A40` for idle. The badges use ink and the text-safe teal and amber.
