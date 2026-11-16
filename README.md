# Earth Defense Force 2 Portable English v0.5

Unofficial fan translation for the original Japanese PSP release, **ULJS-00374**. The builder creates a playable English ISO on your computer using your own disc image. It translates the mission titles and briefings, weapon details and HUD names, menus, and the opening and ending captions. Japanese voices, the original title artwork, and some credit names remain.

v0.5 shortens 39 mission titles, reflows the briefings, and fixes clipped descriptions for the Rapier and Goliath-1. The resulting ISO uses the original game and save IDs.

## Build on macOS

Use Python 3.9 or newer, Apple's command line developer tools, and these three inputs.

- Your unmodified Japanese **ULJS-00374** ISO. The supported image is 382,828,544 bytes and has SHA-256 `8a3541f6185a781a738e162fda8147dcaa436a757914a134a53f4ea662808b06`.
- Luke S's English texture pack. Extract it and select the `ULJS00374` folder containing the `ui` subfolder. [Original texture pack](https://forums.ppsspp.org/showthread.php?tid=28883)
- The pspdecrypt source at commit `c156627db7634d395c380c0a9589130f603307fc`. Extract its source ZIP and select the folder containing `PrxDecrypter.cpp` and `libkirk`. [Pinned pspdecrypt source](https://github.com/John-K/pspdecrypt/tree/c156627db7634d395c380c0a9589130f603307fc)

Unzip the builder and open Terminal in its folder. Create a Python environment and install its dependency.

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
```

Replace the three input paths below with yours. Use a new output filename.

```sh
PYTHON="$PWD/.venv/bin/python" sh build-english.sh \
  "/path/to/your/ULJS00374.iso" \
  "/path/to/ULJS00374" \
  "/path/to/pspdecrypt-c156627" \
  "$PWD/EDF2P-ULJS00374-English-0.5.iso"
```

Compare the printed ISO SHA-256 with `60fb5e5a7437afce2a33c11850c8226f0291bc0456157df3e253926a04d9a401`.

## Play and report issues

Open the generated ISO in PPSSPP. On a PSP with compatible custom firmware, copy it to the Memory Stick's `ISO` folder. If a previous install is present, use the game's **Game Settings → Data Install** menu to replace it with a fresh install from v0.5. Keep your campaign save and relaunch after installing.

The v0.5 ISO loaded a v0.4 test save, completed Data Install, and reached Mission 78 gameplay after restarting in PPSSPP 1.20.4. On PSP-2000 with 6.61 ARK-5 cIPL, the hardware check so far covers Mission 2 on v0.4. The first v0.5 PSP run is pending. The builder has been tested on macOS.

For a bug report, include the version, PSP model and firmware or PPSSPP version, mission or menu, and whether Data Install was in use.

Earth Defense Force 2 Portable is by Sandlot and D3 Publisher. Thanks to Luke S for the English UI texture pack and the pspdecrypt and libkirk contributors for the tools used to build locally. [Original game page](https://www.d3p.co.jp/edf2_psp/) · [Texture pack](https://forums.ppsspp.org/showthread.php?tid=28883) · [pspdecrypt](https://github.com/John-K/pspdecrypt)
