# Capture the remaining antigravity shadow issue

The user confirmed that the RGB565 correction restores cup colours, while the
cyan antigravity shadows remain. Treat this as a separate unresolved issue.
The cup-menu capture does not contain the affected race draws.

Use the same installed APK with the colour fix and the same Turnip/CPU BC
settings. No new APK or shader rebuild is required for this capture. On the
computer with ADB access to the phone, from the repository root:

```bash
git pull --ff-only
python3 devtools/capture_menu.py start --scene shadows
```

Open the game, choose **Time Trials → Mario Kart Stadium**, then drive onto
the banked antigravity section where the cyan kart shadow appears. Release
acceleration and brake to stop there. Leave the race view open and keep the
shadow visible; do not open the pause menu or finish the lap. A trailing banana
is optional: the kart shadow alone is enough for the first investigation.

The capture is scheduled at present 9000, approximately five minutes of
rendering at 30 FPS or 3.75 minutes at 40 FPS after launch. Loading and stalls
can extend that time. Keep the phone awake and connected. After about six
minutes from opening the game:

```bash
python3 devtools/capture_menu.py collect --scene shadows
```

If collection says the scheduled frame has not been reached, remain in the
same view and retry shortly. Send:

```
work/mk8-shadows-capture/mk8-shadows-diagnostics.zip
```

Collection includes the frame trace, completed pass images, logged depth-buffer
`.f32` sidecars, two scheduled game frames and a current Android screenshot.
The pass cap is 96 images, including depth: the final game frames are collected
separately even if a complex frame reaches that cap. Inspect them to verify
that the scheduled capture actually shows the affected section; a later Android
screenshot alone cannot establish that. The temporary slowdown during capture
is not a performance measurement.

Successful collection stops the app and restores the exact settings saved by
start. Reopen normally afterward. To cancel or recover:

```bash
python3 devtools/capture_menu.py restore --scene shadows
```

See [the menu capture guide](MK8_MENU_CAPTURE.md) for ADB device selection,
custom output directories, preservation of newer env.txt edits and retries.
For another attempt choose a fresh output directory on all three commands.
Use `start --scene shadows --frame 12000` if navigation needs more time.
