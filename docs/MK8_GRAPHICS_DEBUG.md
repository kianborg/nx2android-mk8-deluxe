# Mario Kart 8 Deluxe graphics investigation

Device: Nothing Phone (1), Adreno 642L, Qualcomm Vulkan 1.1.128 driver
512.530.0. The tested dump reports game version 3.0.5. Audio and controls work;
the final race picture contains bright rectangular patches.

## Findings

The first capture contains recognizable track, kart and road textures before
post-processing. Final screenshots contain the colored patches. This narrows
the investigation, but does not establish that all earlier textures are correct.
The colored intermediate render targets can also contain intentional material
or normal data; their appearance alone is not proof of corruption.

The second capture requested pass 70. Its frame-6000 trace had passes 0–55, so
no images were dumped then. The request remained pending until present 7762,
when it wrote only pass_00.ppm. Other pass files in that archive were from the
previous run. They must not be compared as if they came from the new frame.
For a future capture of this scene, use a size trigger such as
`DM_VK_PASSDUMP_SKIP=720x404` (the traced first bloom downsample) instead of a
fixed pass number. Verify that the log's dump presents match the intended
frame, and collect only indices actually written in that run. Screenshots are
`frame_006000.ppm` and `frame_006002.ppm`, not `shot_*.ppm`. Size triggers must
be adjusted if the game's internal resolution changes.

Upstream fixes signed BC4/BC5 endpoints to use explicit `signed char`. Android
ARM defaults plain `char` to unsigned. Our former desktop tests passed while
`-funsigned-char` reproduced incorrect signed interpolation. The merged decoder
passes both modes. The trace samples signed BC5 (NVN 0x4c) textures. Their
contents can affect normal maps and lighting; phone testing is required to
measure the effect of this correction on the visible glitches.

## Renderer and driver experiments

| Option | Current support | Purpose |
|---|---|---|
| Qualcomm system Vulkan | Implemented; current default | Baseline after the signed-decoder fix |
| System Vulkan with `DM_VK_UBWC=0` | Existing environment switch | Compare image creation without the framebuffer compression optimizations; may cost performance |
| System Vulkan with `DM_VK_X_NOBC=1` | Existing diagnostic switch | Reissue draw bindings to test the runtime's binding cache; may cost performance |
| Mesa Turnip | Optional `--vulkan-driver ZIP` packaging and AdrenoTools loader | User verified restored menus, Mario and Stadium on Android 15; see TURNIP_TEST.md |
| OpenGL ES | No Android NVN backend implemented | A new backend, not a selectable setting |
| Metal | Apple backend only | Cannot run on this Android phone |

Turnip changes the Vulkan driver, not the NVN rendering backend. The runtime defaults to system `libvulkan.so`; an explicit custom-driver
setting can select a driver bundled with the APK. Use the porter integration
described in [TURNIP_TEST.md](TURNIP_TEST.md), rather than copying a library to
external storage.

First rebuild and reinstall the merged baseline, with temporary capture and
experiment switches removed from env.txt. Compare the same menu and race.
Then test only `DM_VK_UBWC=0`, restart the app, and compare again. Restore it
before separately testing `DM_VK_X_NOBC=1`. Keep the original env.txt and label
each run's log and screenshot. Do not combine switches until their individual
effects are known. These are diagnostic paths, not established fixes.

## Extract translated shaders for inspection

`devtools/extract_graphics_shaders.py` reads shader keys from traced draw lines
and writes just their SPIR-V, binary reflection and a manifest into a ZIP. It
uses a memory mapping rather than loading the whole bundle into Python memory,
checks bundle entry bounds and refuses to overwrite an existing ZIP. It does
not modify the bundle. Prefer the bundle from the same port as the trace;
missing keys are listed explicitly when a different port is used.

```bash
python3 devtools/extract_graphics_shaders.py shaders.dmsv \
    --trace mk8-late-capture/log.txt --output mk8-shader-diagnostics.zip
```

The earlier race trace includes driver-model draw calls (for example vertex
shader `45539f60801ff5e3`, first found in Luigi.szs). Driver-specific shaders
can be shared across characters; this does not identify the selected driver.
The user's Mario is absent both in selection and in races, so Mii placeholder
heads do not account for this symptom. Shader inspection is needed before
attributing the missing models to bone transforms, vertex inputs or fragments.

## Integer vertex register inputs

The supplied shader ZIP confirms a Vulkan input mismatch in driver-model draws.
For example `45539f60801ff5e3` declares location 6 as float4, but the recorded
pipeline supplies NVN RGBA8_UINT / Vulkan R8G8B8A8_UINT there. The shader loads
components, bitcasts them to integer bone indices, and multiplies by 48 to
address its bone matrices. Vulkan requires integer fetch formats to feed
integer shader inputs. Maxwell exposes the integer values as register bits,
which this shader expects to reinterpret, not numerically convert to floats.

The runtime now selects vertex shader variants by the unsigned/signed integer
fetch locations of float-declared inputs. The variants retype those inputs and
bitcast loads back to the original shader values, preserving its math and
matrix indexing. Normalized and half-float attributes retain their original
path. Pipeline/shader caches include the input masks; the pipeline record
version changes to discard incompatible prewarm records. No shader translation
rerun or bundle change is required, but the Android host/APK must be rebuilt.
Logs identify variants with `integer vertex register inputs`.

Fifteen affected combinations from the supplied trace and translated shaders
passed SPIR-V validation after conversion. Synthetic signed/unsigned vector and
component-load cases and variant/cache routing are regression-tested. Rendering
on the phone remains to be verified; this is not evidence that every missing
icon or post-processing artifact has the same cause.

## Driver-data capture and targeted draw probes

The driver-data log has 120 uniform samples, all finite. At present 2177 a
colour draw has 8,064 indices in range 0–1782, within its 32,772-byte position
buffer (12-byte stride). Logged matrices vary over subsequent frames. As a
sanity check, applying the first logged position to each of the first ten
available bone matrices and the logged view-projection matrix puts it within
the camera's clip volume. This is not the actual weighted vertex result: the
log does not capture that vertex's bone indices/weights or the GPU's reads.
It does not prove GPU geometry is correct.

The earlier trace's main driver colour draw uses EQUAL depth comparison, with
depth writes off. A differing pre-pass result can reject the colour draw, but
that has not yet been established on the phone. A diagnostic build supports
`DM_VK_DRAW_PROBE=<vertex shader key>:<mode>` in env.txt, for example
`DM_VK_DRAW_PROBE=45539f60801ff5e3:1`. Only matching draws with a fragment
shader and a noninteger colour target 0 are changed:

| Mode | Change | What a visible character would establish |
|---|---|---|
| 1 | Disable depth testing and depth writes | Depth rejection contributes to the missing draw |
| 2 | Mode 1 plus disable face culling and stencil testing | Culling or stencil may reject it if mode 1 did not reveal it |
| 3 | Mode 2 plus replace the fragment shader with opaque magenta on colour target 0; disable blending/alpha-to-coverage | A magenta mesh demonstrates geometry reaching that colour target when the original fragment path is bypassed |

Use modes in sequence, comparing the same scene. A probe can make objects
visible through other objects: it is a diagnostic, not a gameplay fix. The log
must contain `draw probe: shader ... mode ... applied` before interpreting a
result. Matching some driver meshes does not guarantee every character or
menu icon uses that shader. Remove the setting and restart to restore normal
rendering. Diagnostic pipelines are not recorded for subsequent prewarming.
The embedded magenta SPIR-V is validated and probe-state changes are tested.

## Complete CPU draw packet

The mode-3 character-selection screenshot shows disconnected magenta triangles
around and below the kart, rather than a recognizable driver. This demonstrates
malformed geometry in the selected draw when the original material and rejection
states are bypassed. It does not by itself identify whether the source streams,
skinning, GPU buffer reads or vertex shader execution are wrong. It also does
not explain the Stadium rectangles or missing menu icons.

`DM_VK_DRAW_PACKET=45539f60801ff5e3` requests one indexed colour draw of that
vertex shader. The runtime writes `draw_packet.json`, the referenced vertex
streams, complete bound vertex constant buffers, and its indices into
`DM_ROOT/draw_packet_*.bin`. The snapshot is automatic at the first matching
direct indexed draw, without a fixed frame/pass number. The manifest describes
NVN attribute formats, stream offsets/strides, buffer sizes and uniform register
bindings, and says whether every requested blob was saved. Each blob is limited
to 1 MiB and must lie within a known pool. Unsupported indirect draws are not
captured. Invalid or oversized blobs produce an incomplete packet and a red log
line rather than an out-of-bounds read. Only one packet is attempted per launch.

These are CPU-side replay inputs, not a GPU readback. Uniforms include pending
host updates through `vk_ubd_read`; vertex streams and indices are guest-memory
copies. The capture does not alter draw state or shaders. The request is off
unless explicitly present in env.txt. Capturing the indices, weights and full
bone palette together enables offline reconstruction that the earlier partial
uniform logs could not support. Use the manifest to select files from a run;
older unused packet files can remain on disk.

## Offline reconstruction result

The uploaded complete packet at present 685 has 8,088 indices referencing
1,818 vertices (indices 0–1817). All referenced vertices have byte weights
summing to 255; every weighted bone reference is within the 33-matrix palette.
Reference linear-blend skinning produces a recognizable driver mesh rather
than the scattered triangles of the magenta GPU probe. This establishes that
these CPU-captured inputs are internally consistent. It does not validate the
full translated vertex program, GPU uploads, descriptor bindings or GPU reads.

Reproduce with `python devtools/analyze_draw_packet.py <extracted packet>`.
The tool is explicitly limited to the inspected shader and input layout, checks
stream bounds and file paths, and writes a JSON report and orthographic
wireframes beside the packet. Its weighted transform, base-vertex handling,
strides and input bounds have a synthetic regression test. Captured game data
and generated images remain outside the repository.

A next comparison can use the existing `DM_VK_DYN_UBO=0` startup setting to
remove dynamic uniform-buffer descriptors/offsets while retaining the shaders
and their constant data. This is distinct from the previously tested draw-bind
cache switch. Start from the original env.txt, without the magenta probe or
packet capture enabled, and compare the same character menu and circuit.
This is a diagnostic comparison, not an established fix or proof of a driver
bug. It requires an app restart but no host/APK rebuild.

## Copied-buffer and static-uniform results

Neither the static-uniform comparison nor the no-zero-copy comparison restored
the character. The copied-pool log confirms fallback -4 and copied allocations;
the screenshot still shows malformed coloured geometry, at about 1 FPS. This
fallback is not a practical workaround. The CPU-side vertex reference and a
scalar interpreter of the supplied SPIR-V (including its integer-input variant)
agree over 1,818 referenced vertices, within about 7.5e-6 in clip coordinates.
That still does not prove GPU reads/execution match the CPU model.

An optional AdrenoTools/Turnip path is now available for a driver comparison.
The code validates driverID 18 after device enumeration, so a loader that
silently falls back to Qualcomm cannot count as a successful Turnip trial.
The helper libraries build for ARM64 and a real Turnip ZIP has been packaged
into a signed test APK in the cloud; that packaging test is not device testing.


## Successful Turnip device comparison (2026-10-31)

The user reports that the game now works with the packaged revision 9v2 driver.
The supplied mk8-turnip-log.txt confirms Mesa 24.3.0-devel (git-4497ea2a31),
Vulkan 1.3.296 and driverID 18, with no `[RED]` entries. The Photos-1-001.zip
screenshots show restored menus, character icons, Mario, vehicle parts and cup
previews. The Stadium screenshot shows Mario, race HUD icons and no large
coloured rectangles, with a 30 FPS counter. This is a short device test, not a
sustained performance measurement or exhaustive game compatibility result.

Working settings are `DM_VK_DRIVER=turnip` and `DM_VK_BC_DECODE=1`, with prior
probes and copied-buffer experiments disabled. The comparison also disabled
pipeline caching via `DM_VK_NOPCACHE=1`; this can be removed after saving the
working configuration. Keep CPU BC decoding enabled for the runtime's generated
BC texture shadow path. See [TURNIP_TEST.md](TURNIP_TEST.md) for the exact
package and setup. The evidence establishes a driver-dependent workaround,
not the precise internal cause of the Qualcomm failures. User captures remain
outside the repository.


## Remaining visual issues in the Turnip follow-up screenshots

The user's subsequent Photos-1-001.zip contains two screenshots:

- Screenshot_20261031-153700.png: on Stadium's banked antigravity section,
  bright cyan silhouettes lie on the road beneath/behind the kart and trailing
  banana. Their colour and hard edges are suspicious for a projected shadow
  or related effect. A still image does not establish the exact responsible
  draw, whether it flickers, or whether the fault is limited to antigravity.
- Screenshot_20261031-152254.png: the cup-selection background is normally
  blue, but yellow symbols (Star, Banana, Lightning and Triforce) appear cyan,
  and the Mushroom symbol looks purple. The track preview thumbnails retain
  plausible colours, as do the yellow selection brackets and buttons. This is
  selective colour corruption, not evidence for changing the entire frame's
  colour balance.

A common texture-channel or intermediate render-target issue is worth testing,
but the screenshots do not prove the two effects share a cause. Inspection of
Vulkan blend-factor/equation conversion found those mappings consistent with
NVN's enum definitions; this does not validate the states of the affected draws.
Next evidence should be a bounded pass/texture capture of cup selection first
(a stationary reproducible screen), followed by the affected antigravity frame.
Compare each affected texture, its view swizzle/format and the first pass that
introduces the wrong colours. Keep the working Turnip and CPU BC settings;
do not apply a global red/blue swap or disable CPU BC decoding as a workaround.
No runtime fix has yet been validated for these follow-up issues.

## Cup-selection capture: reversed RGB565 channels

The supplied mk8-menu-diagnostics.zip contains a complete frame-6000 trace and
48 completed pass images, all logged at present 6000. Pass 38 (pass_45.ppm)
still shows the patterned background without the cup UI. Pass 39
(pass_46.ppm) adds the UI, including the cyan symbols. The incorrect colours
are already present before pass 40 scales/presents the image (pass_47.ppm).
The trace binds the twelve 200x200 cup colour textures as NVN RGB565 (0x3c),
paired with separate BC4 masks. Their Vulkan images use format 4,
R5G6B5_UNORM_PACK16. This isolates a format-table error rather than a global
presentation colour adjustment or BC colour-decoder fault.

NVN RGB565 stores red in the low five bits and blue in the high five bits.
Vulkan's packed format names put the first component in the high bits, so the
correct direct-storage mapping is B5G6R5_UNORM_PACK16 (format 5). The previous
mapping swaps red and blue: yellow becomes cyan, red becomes blue and green
is unchanged. NVN BGR565 (0x95) needs the inverse mapping; both entries are now
corrected without shader or game-specific changes. The existing Metal format
table independently handles NVN RGB565 with a red/blue remap.

A regression exercises the actual Vulkan format selector with packed red,
yellow, green and blue pixel values, including the inverse BGR565 layout. It
fails with the previous table and passes with the corrected one. Device
confirmation remains pending: rebuild the host/APK with the same Turnip ZIP
and signing key, retain the working env.txt and compare cup selection. Shader
regeneration is unnecessary. The antigravity shadow appearance is not yet
explained by this capture or confirmed fixed by the format correction.

## RGB565 device confirmation and remaining shadow investigation

The user confirmed that the corrected build fixes the cup-selection colours.
The antigravity shadow issue remains on that same build, so correcting the
RGB565 mappings did not resolve it. The next evidence is a stationary Time
Trials frame on Stadium's affected banked section, with pass images, a draw
trace and depth values. [MK8_SHADOW_CAPTURE.md](MK8_SHADOW_CAPTURE.md) describes
the release-APK capture. No shadow-state, shader or texture workaround is yet
justified by the menu-only trace.

## Antigravity capture at present 9000

The supplied mk8-shadows-diagnostics.zip contains the affected banked Stadium
view at presents 9000 and 9002, 67 completed pass images from present 9000,
and numeric depth sidecars. There are no `[RED]` entries. Shadow-depth passes
4 and 5 (pass_05/06.ppm) contain a recognizable kart/driver silhouette; this
confirms generation, not correctness of every depth value or later lookup.

Pass 16 writes an RGBA8 lighting/shadow mask at pool offset 0x6f0600, using
fragment 6aa6c36ed6065b7d and a two-layer D16 comparison texture. Pass 17 adds
projected masks with fragment shaders be891424dfb3f8e0 and eda8130f8a9a7634.
The latter draws multiply only red by one-minus-source-alpha. Cyan pixels in
this intermediate image are not by themselves corruption: its channels carry
separate mask data. Pass 18 samples this mask and renders the scene; the
unwanted cyan silhouette is already visible in pass_26.ppm, before bloom or
presentation. The supplied shader-map origins identify these as common AGL
shadow/projection shaders. Exact shader execution and sampling still need
inspection before choosing a runtime fix.

The capture contains shader keys, not the shader programs themselves. With
the same APK/data pack installed and the phone connected, retrieve just the
trace's shader entries without replaying the race or pulling the full 671 MB
bundle:

```bash
python3 devtools/extract_device_shaders.py \
  --trace work/mk8-shadows-capture-2/log.txt \
  --output work/mk8-shadow-shaders.zip
```

The extractor reads the header/table and block-aligned ranges through ADB,
validates bounds and writes only selected SPIR-V/reflection entries plus a
manifest. It does not change env.txt or require the game to be running. Local
sparse staging preserves bundle offsets for the existing validated extractor.
Tests cover entry bounds, duplicate keys and a mocked ADB-to-ZIP extraction.
Send the resulting ZIP for the next shader analysis. This is diagnostic data,
not a shadow workaround.

## Supplied shadow shader analysis

The user supplied all 171 shader keys referenced by the antigravity trace,
with no missing entries. The common resolve (6aa6c36ed6065b7d) and projected
mask fragments (eda8130f8a9a7634, be891424dfb3f8e0) pass spirv-val for Vulkan
1.1 with scalar block layout. Projected masks explicitly write RGB zero and
compute alpha, matching their destination-darkening blend factors. The resolve
uses a D16 array comparison sampler and writes independent mask channels;
coloured intermediate silhouettes are therefore not sufficient evidence of
incorrect colour output. No validated runtime correction follows from static
shader inspection alone.

A bounded `--shadow-test map-off` capture now isolates the resolve vertex
shader through existing runtime skip support, without repacking the APK. See
[the controlled comparison](MK8_SHADOW_CAPTURE.md#controlled-shadow-map-comparison).
This is an A/B diagnostic, not a shipped shadow fix. Keep the RGB565 fix and
working Turnip/CPU BC settings throughout, restoring the diagnostic switch
after collection.


## Map-off result and upstream sync

The supplied mk8-shadows-map-off-diagnostics.zip records the map-off setting and
omits the targeted resolve draw. The scheduled image shows a broadly cyan road,
so this experiment cannot isolate the original silhouette visually. Removing
the draw does not supply a neutral lighting mask. No conclusion that the
shadow-map resolve itself is defective follows from this result.

Upstream was synced through 0d0468dd2ec1872700ece91fc8aba7c43b350825:

- 7402e8c snapshots sampler registrations as seen by each bind, preventing later
  re-registration of a sampler ID from changing earlier recorded draws. It also
  zero-pads direct vertex-stream reads past the bound size. Both are relevant
  general rendering corrections, but neither is yet a verified MK8 shadow fix.
- a318ff8 writes linear render targets back for CPU readers. It fixes a source
  of stale CPU-visible simulation data in Odyssey; applicability to this MK8
  scene has not been demonstrated.
- 0d0468d builds eligible graphics and compute pipelines in the background and
  moves pipeline-record writes off the replay lock. It may reduce compilation
  stalls; gains on this phone remain unmeasured. The fork also exempts generated
  BC targets from skipped first-use draws because their blocks are read back
  and decoded on the CPU after the pass, like upstream's linear-target guard.
- 60857c8 implements the vibration-device mounted query in the host.

The merge preserves the packaged Turnip loader, forced BC decode, corrected
RGB565 formats and shader variants for integer inputs/depth conversion. Conflict
resolution retains upstream profiling and compute-pipeline race handling while
keeping the fork's extended variant API and excluding diagnostic probe pipelines
from persistent prewarm records. The regression suite passes 101 tests and the
Android release build compiles 142 sources with zero failures. The next phone
test should use this synced baseline with the map-off diagnostic removed; there
is no justified additional shadow patch yet.

## First race-entry crash after the upstream merge

The user reports one crash entering Time Trials on first boot after updating,
then successful launches, with antigravity shadows still incorrect. There is
no crash log yet; background pipeline compilation, driver faults and memory
pressure are hypotheses, not established causes. A successful warm-cache
restart cannot discriminate among them.

`python3 devtools/collect_crash.py` reads the current game log/settings, Android's
crash buffer (last 2000 records) and the package's historical exit information.
It writes a timestamped diagnostic ZIP without stopping the app, clearing logs,
changing settings or removing caches. Collect now while historical records may
remain, and immediately after another crash before reopening the game. Logs
may have expired, and the current game log may already belong to the successful
restart; absence of a crash there is not proof of its cause.

A reversible comparison can add `DM_VK_ASYNC_PIPE=0` and `DM_VK_NOPREWARM=1` to
an otherwise preserved working env.txt, then restart. The first disables
first-use background graphics compilation; the second disables graphics and
compute prewarm workers. This comparison can increase startup/loading stalls.
Do not delete shader/pipeline caches or app data to force a crash before the
initial report is examined. Warm-cache success alone cannot prove the fix.
Keep Turnip and forced CPU BC decoding enabled. Do not combine this comparison
with the rejected shadow-map-off experiment.


## First crash-history report

Android's package-specific exit history records EXIT_SELF/status 139 for the
reported app. The runtime's crash.c catches signals and calls `_exit(128+sig)`,
so this is consistent with a caught SIGSEGV, not proof of its faulting module or
of background compilation as the cause. The collected Android native crash
traces belong to different packages and must not be attributed to MK8. A much
earlier low-memory record does not establish the cause of this latest exit.
The collected current game log belongs to a later running session and contains
no crash dump. Its env.txt still enables prewarm/async defaults; the suggested
synchronous comparison has not been established by this report.

The Android front end rotates log.txt to log.prev.txt on launch. The collector
now includes that previous log, which was omitted initially. Retrieve it before
another launch overwrites it. No runtime crash fix is justified until the
faulting address/thread or equivalent evidence is available.

## Previous-run crash: Turnip KGSL submission error cleanup

The supplied mk8-previous-log.txt contains `CRASH sig=11 addr=0x28`,
PC/LR 0x6d99e7ddc0, and x23=0. The retained revision 9v2 Turnip ELF has a
static symbol table. Testing page-aligned load bases against the five recorded
driver return addresses found one base with call instructions at all five
return sites: 0x6d99886000. At this base the backtrace resolves to:

- PC +0x5f7dc0: kgsl_queue_submit
- +0x61633c: vk_queue_submit_final
- +0x60e9c8: vk_device_flush
- +0x617408: vk_queue_submit
- +0x61681c: vk_common_QueueSubmit2
- +0x61eb30: vk_common_QueueSubmit

The faulting instruction is `ldr x8, [x23, #0x28]`, matching the null x23 and
fault address exactly. Mesa source for the logged revision,
[tu_knl_kgsl.cc at 4497ea2a31](https://github.com/chaotic-cx/mesa-mirror/blob/4497ea2a31/src/freedreno/vulkan/tu_knl_kgsl.cc),
contains an unconditional dereference of optional u_trace_submission_data in
fail_submit cleanup after a failed GPU_COMMAND ioctl. The disassembled binary
likewise calls device-set-lost before entering this cleanup. This is strong
evidence for a secondary driver cleanup fault after submission failure, not
proof of the submission's original cause (driver issue, invalid GPU work,
resource failure, etc.). It does not establish a compilation-thread crash or
that the runtime's submitted work was valid.

The game log does not contain Mesa's original submission error. collect_crash.py
now uses the package-specific exit history to select the failed status-139 PID
and retrieve its normal Android log messages as android-failed-process.txt.
Retained Android logs may have expired. It still does not alter settings or
caches. crash_off now includes native library name/base-relative offsets even
when dladdr has no symbol name; the existing symbol and raw-address fallbacks
are preserved and regression-tested. This formatter change requires a host
rebuild for future logs; the collector update does not.

No driver-binary patch is applied: avoiding the cleanup dereference alone would
not repair failed GPU work. No claim that this explains the antigravity shadow
issue follows from this crash analysis.

## Extended historical logs and synchronous stability comparison

The follow-up ZIP retrieved Android records for the correct failed PID, 30045,
but contains only activity/events and startup audit records; no retained Mesa
submission failure or errno is present. It does not discriminate between
invalid submitted work, driver failure or a resource problem. Recollecting the
same historical session is not the next diagnostic step.

A reversible stability comparison is available without an APK rebuild:

```bash
python3 devtools/pipeline_stability.py start
```

It backs up the current env.txt, retains Turnip and CPU BC settings, stops the
app and sets ASYNC_PIPE=0 / NOPREWARM=1. It preserves caches and saves and
rejects an active shadow-skip experiment. Enter Time Trials normally. A
successful warm-cache run does not prove a first-run crash fixed; leave the
configuration in place for ordinary play and collect immediately if it recurs,
before relaunching. The earlier shader/pass evidence remains available for the
separate unresolved antigravity issue; this setting is not a claimed shadow fix.

Restore with `python3 devtools/pipeline_stability.py restore`; restoration
checks that env.txt has not changed since start. Use the same `--output` folder
for both actions if a fresh backup folder is needed. No pipeline cache clearing
is requested. The helper's settings preservation and rejection cases are tested.

## Next shadow investigation: paired resolve inputs/output

The earlier packet diagnostic saved vertex constants only and could trigger on
a menu draw before reaching the race. It now accepts DM_VK_DRAW_PACKET_AT and
saves vertex and fragment constants separately (stage-tagged records). The
bounded one-shot packet is paired with the frame-9000 pass capture. The helper's
uniforms mode also selects the resolve's sampled RG32F input by shader/binding,
preserves its exact float pairs, and saves mask RGBA8 values including alpha.
This closes concrete data gaps in the earlier pass-image-only capture without
repeating the inconclusive map-off test. See MK8_SHADOW_CAPTURE.md.

Regressions cover delayed capture, stage-separated deferred uniform reads,
bounded packet blobs, collection of negative-numbered sampled-texture passes,
raw sidecars and rejection of unsafe/missing packet files. The full suite passes
106 tests and the Android release library compiles 142 sources with no failures.
Phone validation of the new diagnostic capture remains pending.

## Uniform capture recovered from the user's 7z archive

The uploaded mk8-shadows-uniforms-capture.7z decompresses successfully. It
contains a complete frame-9000 resolve packet manifest, pass/depth data, exact
2048x2048 RG32F input and raw RGBA8 masks. The packet identifies the intended
vertex/fragment pair, six indices and one 128-byte vertex stream. Both stage
constant buffers were saved at 608 bytes, but their blobs were not pulled.

The collector incorrectly required fragment register 3, inferred from a shader
variable name. The actual reflected fragment binding is 4 and its runtime
register is 0. That faulty validation rejected a valid packet before pulling
its four binary files. Validation now checks stage 1 / binding 4, independently
of register numbering; an exact structural regression covers this manifest.
No runtime or shader rebuild is needed for this correction.

Re-running collect with the same uniforms capture directory retrieves the
saved packet blobs and also writes a small mk8-shadow-inputs.zip containing
the packet, trace and capture metadata. Only this small archive is needed next;
the large pass data is already available. Avoid relaunching the game before
retrieval so another armed capture cannot replace the saved files.

The recovered RG32F texture has finite nonconstant values (R 0.18205562..1,
G 0.03318596..1), so it is not an empty input. The post-resolve RGBA mask has
constant red 128, varying green/blue and alpha 255, consistent with independent
mask channels rather than directly displayed surface colours. These facts do
not establish why subsequent material shading produces the cyan silhouette.
The missing stage uniforms are still needed for the planned numeric comparison.
