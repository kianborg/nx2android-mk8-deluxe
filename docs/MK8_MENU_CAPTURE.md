# Capture the remaining cup-symbol colour issue

This uses the installed release APK's existing diagnostics. No APK rebuild or
shader repack is needed. Use the computer with ADB access to the phone.
Keep the phone connected and awake throughout. The capture may briefly stall
rendering and produces intermediate images; its frame rate is not a benchmark.

Update the fork, then run these commands from its root:

```bash
git pull --ff-only
python3 devtools/capture_menu.py start
```

Open the game manually, go directly to the cup-selection screen, select the
Mushroom Cup and leave it there. Do not start a race. The capture occurs at
present 6000: approximately 2.5 minutes of rendering at 40 FPS or 3.3 minutes
at 30 FPS. Loading and stalls can increase that time. After about four minutes:

```bash
python3 devtools/capture_menu.py collect
```

If collect says it has not reached the scheduled frame, keep that screen open
and retry shortly. ADB must target the same phone for every command; pass
`--serial SERIAL` if more than one device is connected. Use `--adb PATH` if
ADB is not on PATH. All subcommands accept these options.

On success, collect saves `work/mk8-menu-capture/mk8-menu-diagnostics.zip`, stops the
app and restores the exact env.txt backed up before the test, including the
working Turnip/CPU BC settings. Reopen the game normally afterward. Send the
ZIP for analysis. Its log and intermediate pass images identify where to
inspect source textures next; this first capture does not automatically dump
every sampled texture or establish the cause of the colour issue.

To cancel or recover after any failure:

```bash
python3 devtools/capture_menu.py restore
```

The original settings remain in `work/mk8-menu-capture/env-before.txt`. Restoration
refuses to overwrite env.txt if it was edited since start. In that case merge
any newer changes with that backup manually. Never restore the older
pre-Turnip probe backup for this test.

Each attempt needs a new output directory (the helper refuses to overwrite
an existing backup). Supply the same `--output DIRECTORY` on start, collect
and restore. `start --frame 9000` allows more navigation time if needed.
Only pass indices recorded as complete in the new run's log are collected;
old pass files on the phone are excluded. No game data pack or saves are pulled.
