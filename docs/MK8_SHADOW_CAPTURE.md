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

## Controlled shadow-map comparison

Result: the user's supplied map-off capture makes the road cyan across the
view. The resolve draw is absent from the trace as requested, but its removal
leaves no valid neutral replacement for the lighting mask. This comparison is
inconclusive for the original silhouette; do not treat it as a workaround or
repeat it as the next test. After syncing upstream, test the rebuilt APK with
normal shadow rendering and the working Turnip/CPU BC settings restored.


The captured shadow shaders validate as Vulkan 1.1 SPIR-V. The projected decal
fragment shaders write zero RGB and compute opacity in alpha. Their recorded
ZERO / ONE_MINUS_SRC_ALPHA blend is consistent with darkening a channel mask.
This does not establish that their inputs or subsequent lighting are correct.
The common shadow-map resolve writes separate values to each mask channel;
its cyan/purple intermediate appearance is not itself a colour-rendering bug.

To distinguish that resolve path from projected decals and later lighting,
the helper can arm an explicit A/B experiment using the runtime's existing
`DM_VK_X_SKIPVS` support. In the supplied frame, vertex shader
b2cfa260c7494f18 occurs only in the shadow-map resolve draw (fragment
6aa6c36ed6065b7d). The test skips draws using that vertex shader; projected
decals, geometry/depth generation and later material draws remain enabled.
This intentionally removes a rendering operation and is not a permanent fix.
No APK or shader rebuild is required.

```bash
python3 devtools/capture_menu.py start --scene shadows --shadow-test map-off
```

Repeat the Time Trials positioning described above. After about six minutes:

```bash
python3 devtools/capture_menu.py collect --scene shadows --shadow-test map-off
```

Send `work/mk8-shadows-map-off-capture/mk8-shadows-map-off-diagnostics.zip`
and report whether the cyan silhouette vanished, changed, or stayed the same.
If this output folder already exists, specify a fresh `--output DIRECTORY` on
both commands. Successful collection restores the pre-test settings. To cancel:

```bash
python3 devtools/capture_menu.py restore --scene shadows --shadow-test map-off
```

If the silhouette disappears, the resolve or its consumption is implicated;
that alone does not prove which is incorrect. If it persists, focus on the
other draws rather than treating removal of shadow-map sampling as a fix.
