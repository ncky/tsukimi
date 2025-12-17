# Tsukimi for Steam (MetroSteam patcher)

This folder contains a small patcher script that applies the **Tsukimi (dark)** color palette to the **MetroSteam / “Metro by Rose”** Steam skin.

This repo does **not** ship MetroSteam’s files. You install MetroSteam separately (https://github.com/RoseTheFlower/MetroSteam/), then run this patcher against your local MetroSteam install folder.

## Requirements

- Python 3
- A MetroSteam install folder that contains:
  - `libraryroot.custom.css`
  - `friends.custom.css`
  - `notifications.custom.css`
  - `webkit.css`
  - `theme.json`

## What it changes

- Updates MetroSteam’s theme variables (backgrounds, borders, text, accent) to match Tsukimi.
- Adds a `Tsukimi` entry under `Variation` in MetroSteam’s `theme.json` so you can select it in theme tools that read that file.
- Sets the Friends list + Chat outer borders to `1px`.

## Install MetroSteam (summary)

MetroSteam is a Steam skin and generally needs a skin loader/patcher to inject CSS into Steam.

Typical flow (paraphrased from MetroSteam’s README ):

1. Close Steam completely.
2. Put MetroSteam into Steam’s skins folder (commonly `Steam/steamui/skins/`).
3. Use a compatible injector/loader (for example SFP/CSSLoader/Millennium) to enable the skin, then restart Steam.

The exact steps depend on which loader you use and where Steam is installed on your system.

## Run the Tsukimi patcher

From this folder (or anywhere):

```bash
python3 ./patch_tsukimi.py /path/to/Steam/steamui/skins/MetroSteam
```

Helpful options:

```bash
# show what would change, without writing
python3 ./patch_tsukimi.py --dry-run /path/to/Steam/steamui/skins/MetroSteam

# patch without backups
python3 ./patch_tsukimi.py --no-backup /path/to/Steam/steamui/skins/MetroSteam
```

By default, the script writes timestamped backups into `/path/to/Steam/steamui/skins/MetroSteam/_tsukimi_patch_backups/`.

## After patching

1. Restart Steam (and re-inject the skin if your tool requires it).
2. If your loader exposes MetroSteam’s `Variation` dropdown, select `Tsukimi`.

## Reverting

Restore files from the `_tsukimi_patch_backups/` folder (or reinstall MetroSteam).
