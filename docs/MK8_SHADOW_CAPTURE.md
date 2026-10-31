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

## Capture shadow resolve inputs without disabling rendering

Use `--shadow-test uniforms` for the next investigation. This requires an APK
rebuilt from the extended diagnostic source (same Turnip ZIP and signing key),
but no shader regeneration. Keep normal shadow rendering enabled and retain
working Turnip/CPU BC settings. Any synchronous pipeline settings already in
place are preserved by this capture and its restoration.

```bash
git pull --ff-only
# Rebuild/reinstall the APK using the existing Turnip-enabled port command.
python3 devtools/capture_menu.py start --scene shadows --shadow-test uniforms
```

Repeat the Time Trials positioning described above and keep the affected view
open. After about six minutes from launch:

```bash
python3 devtools/capture_menu.py collect --scene shadows --shadow-test uniforms
```

Send `work/mk8-shadows-uniforms-capture/mk8-shadows-uniforms-diagnostics.zip`.
The helper restores the pre-capture settings after collection. Use matching
`--output DIRECTORY` options on both commands for another attempt. Cancellation
uses `restore --scene shadows --shadow-test uniforms` with the same directory.

This preserves the normal rendering operation and collects:

- A delayed CPU replay packet for resolve vertex shader b2cfa260c7494f18, with
  separate vertex and fragment constant buffers. `stage` distinguishes buffer
  entries; existing vertex buffer filenames stay compatible. Each blob remains
  bounded to 1 MiB. The packet reflects intended CPU replay data, not GPU UBO
  readback, and is attempted once at/after present 9000.
- The fragment shader 6aa6c36ed6065b7d's binding 2 source texture. The observed
  2048x2048 RG32F image is copied exactly, without half-float conversion, and
  written as interleaved float pairs in a pass `.f32` sidecar. This diagnostic
  source path accepts a single-layer RG32F image up to 64 MiB. Its pass number
  is -100, distinct from the output image index in the filename.
- Ordinary pass/depth outputs plus exact `.rgba8` bytes for RGBA8 targets,
  retaining the alpha channel that PPM previews omit. The trace supplies image
  dimensions and format. RG32F/RG16F PPM previews use a signed-field display
  scale; numerical analysis must use the `.f32` files, not those preview colours.

The collector rejects incomplete/mistimed shader packets, requires the fragment
constant buffer, and collects only files recorded by the new run's log. These
inputs support a CPU reference of the shadow resolve and comparison against
its output mask; they do not alone establish that uploaded GPU UBO bytes match
the CPU view. No shadow compatibility patch is enabled by these switches.

If collection from the extended capture reported missing fragment uniforms,
update the source and rerun the **collect** command for the same directory.
The earlier collector incorrectly required register 3; the shader's constants
are at fragment binding 4 / register 0. An already completed capture does not
need another APK rebuild or race run to recover those files. Collection now
also creates `mk8-shadow-inputs.zip`, a small packet-and-log archive suitable
for upload when the pass images have already been supplied separately.
