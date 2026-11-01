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

## Numeric resolve comparison and texture-view channel correction

The recovered packet contains the two 608-byte stage buffers and the expected
fullscreen indices/vertices. A scratch NumPy reference follows the captured
resolve's depth reconstruction, cascade projection, D16 comparison sampling,
RG32F moment lookup and variance/fade equations. It uses float32 intermediates
and float64 product-plus-add rounded to float32 for FMA, ordinary bilinear
weights, and the captured layer-0 depth. It is a numerical reference of these
equations, not a complete SPIR-V interpreter or bit-exact GPU sampler model.

Against pass_27's raw mask, the near-cascade green channel is within 1.1 byte
units for 99.82% of near-cascade pixels. All 16,290 captured zero-green shadow
pixels agree with reference visibility below 0.01. Restricting to nontrivial
shadow/edge pixels gives 97.33% within that tolerance. The blue variance channel
is within 1.1 units for 99.14% of the full frame (89.32% in its nontrivial
region; mean error there 0.64 units). A deliberately reversed screen-Y reference
matches much worse. These results support correct generation of the core mask
silhouette and narrow attention to consumption; they do not prove every lookup
or edge is exact. The depth dump currently reads array layer zero, so this is
not a validation of the far cascade.

While tracing mask consumption, the Vulkan view code was found to compose the
texture's selectors with the view's selectors. NVN view selectors override the
texture selectors; they then map through the selected format's component
mapping once. The existing Metal implementation follows that rule. A parent
that replicates red and a view selecting green previously read parent-red
instead of original-green. For multichannel masks this can select unrelated
mask values. The correction chooses view selectors when explicitly set,
otherwise texture selectors, and applies only the format mapping afterward.
Attachment views retain identity selectors as Vulkan requires. Format-level
constant alpha and red/blue remaps are preserved.

The regression fails with the prior composed behavior and passes with the
correction, covering explicit identity overrides, parent fallback, constants,
format remaps and attachment identity. Full regression: 108 tests passed;
Android release: 142 sources, zero failures. Sampled-channel selectors are now
logged in an explicitly traced frame, to establish the actual mappings if a
future capture is needed. The earlier trace lacks this metadata, so this is a
validated general semantic fix and a plausible shadow-related candidate, not
a confirmed resolution of the phone's cyan silhouette. Rebuild/reinstall with
the same Turnip ZIP/signing key and check the affected race normally first;
no additional six-minute diagnostic capture is requested yet.

## Device confirmation: shadow fixed; antigravity wheel flicker remains

The user confirms that the texture-view swizzle correction (18886dd) fixes the
cyan shadow problem on the phone. They now report minor flicker around the
wheels in antigravity. That temporal issue has not yet been captured or assigned
to a particular draw. A short recording with a stationary kart/camera should
first distinguish wheel geometry, cyan glow, road reflections and overlapping
transparent effects. Keep the confirmed Turnip/CPU BC and swizzle fixes; do not
apply a new depth, blend or driver workaround without that evidence.

## Direct recording: antigravity illumination flicker

The user supplied mk8-wheels.mp4 (2400x1080, 291 video frames over about 9.76 s).
It confirms that the changing wheel illumination is present in direct screen
output, not solely in the earlier filmed-display clip. Consecutive frames show
changes in cyan illumination on the tire bodies/nearby kart surfaces while
silhouettes and rim lines remain stable. The recording alone cannot identify
the responsible pass or distinguish an incorrectly animated light from a
GPU depth/synchronization problem.

The earlier trace identifies a relevant half-resolution local-light pass:
fragment 0722cc0403877a4e, 480x270, two colour targets, depth GREATER, and the
runtime's fragment-depth variant enabled. Its depth attachment was written by
a shader in the preceding downsample. The automatic variant writes FragCoord.z
to FragDepth to address Adreno LRZ issues; it is also selected with the current
Turnip driver. That is a concrete candidate for a one-switch comparison, not
evidence that the variant causes this flicker.

No APK rebuild is needed for this comparison:

```bash
git pull --ff-only
python3 devtools/pipeline_stability.py start --test wheel-depth
```

This backs up env.txt and changes only DM_VK_FDZ to 0, preserving the existing
pipeline switches, Turnip and CPU BC configuration. Reopen Time Trials, stop
at the same antigravity position and report whether the illumination remains
visible and steady, disappears entirely, or still flickers. A missing effect
is not a successful fix. There is no six-minute pass-dump wait for this test.
Restore with:

```bash
python3 devtools/pipeline_stability.py restore --test wheel-depth
```

Restoration refuses to overwrite newer settings; the original backup is in
work/mk8-wheel-depth-test/env-before.txt. The helper's one-switch preservation
and invalid-test rejection are regression-tested. A new random crash was also
reported alongside the first wheel clip; no new crash evidence has been
provided with the direct recording, so it remains a separate open report.

## Wheel-depth comparison negative; temporal lighting capture

The user reports that DM_VK_FDZ=0 still flickers. This makes that automatic
fragment-depth variant a less likely explanation; it is not proof that all
depth testing or synchronization is correct. Restore the comparison before
another experiment. The confirmed texture-view fix remains in place.

The direct screen recording establishes that brightness changes persist in
rendered output while the tire outline/rim lines are stable. The single-frame
pass trace cannot establish which pass changes between bright and dark states.
A new helper mode, `--shadow-test wheel-light`, uses the installed runtime's
existing size/format filters to record half-resolution local-light targets and
matching final frames for 16 scheduled presents. It enables no draw skipping
or shader modification. It selects 480x270 or 640x360 colour targets with first
two recorded formats 122/122, which also admits matching bloom intermediates;
the trace/pass IDs distinguish them. Only colour target zero is dumped in this
first comparison, not both MRT outputs. It is not a complete validation of the
specular attachment. At most 96 intermediate images are retained; collection
requires at least eight distinct presents to avoid accepting a one-frame dump.

No APK rebuild is needed:

```bash
git pull --ff-only
python3 devtools/pipeline_stability.py restore --test wheel-depth
python3 devtools/capture_menu.py start --scene shadows --shadow-test wheel-light
```

Enter Time Trials at the same stationary antigravity view and leave it open.
After about six minutes from launch, collect:

```bash
python3 devtools/capture_menu.py collect --scene shadows --shadow-test wheel-light
```

Send `work/mk8-shadows-wheel-light-capture/mk8-shadows-wheel-light-diagnostics.zip`.
The helper restores its original env.txt on successful collection. If a capture
error occurs, preserve the directory and log rather than rerunning the race;
existing pass files may suffice. GPU readbacks/frame shots alter timing, so a
capture in which flicker disappears cannot alone establish a fix. The next
analysis compares changing light targets with the final wheel illumination;
there is not yet a justified runtime flicker patch.


### Wheel-light capture received: submission comparison

The returned `mk8-shadows-wheel-light-diagnostics.7z` contains all 16 scheduled
final frames (9000–9015), 25 intermediate colour dumps, the trace, and the
original/capture settings. The final frames reproduce the wheel illumination
change while the rim outlines remain stable. The captured light targets also
change coverage: some show larger cyan regions on the wheels, others mostly
thin rings. Thus the difference already exists before final composition;
this does not yet identify the failing draw or distinguish bad inputs from
incorrect depth rejection. Only target zero was captured.

The original exact-size capture filter was incomplete. The traced local-light
pass at present 9000 is 482x271, with scene targets 965x543. Other presents
produce 480x270 or 640x360 dumps. The game changes render resolution, so missing
dumps at intermediate dimensions cannot be interpreted as missing passes.
Do not repeat the same size-filtered capture expecting a complete temporal
sequence. Pass numbers also move. The final images contain a 1280x720 active
view in a 1920x1080 image; crops must account for that.

The log reports no missing-program, missing-target, or missing-pipeline draw
skips through present 9000. The traced light-volume draw uses vertex shader
35696712904ac390 / fragment shader 0722cc0403877a4e, two R11G11B10 targets
(array layers 0 and 1), and D32 depth, GREATER test, no depth writes. Its
fragment-depth workaround is enabled in this capture. The earlier FDZ=0
comparison still flickered, so neither FDZ setting has established a fix.

The next isolated comparison is ordinary command-buffer splitting. The
existing renderer comments in `gfx_vk_exec.c:begin_pass` describe transient
light loss in other games when a later pass reuses depth from before a draw-count
split, even with LRZ invalidation touches. That is a reason to test this path,
not evidence that MK8 has the same cause. `--test wheel-submit` changes only
`DM_VK_CB_DRAWS=0`; required submission boundaries and any explicitly configured
pass splitting remain. No renderer patch, APK rebuild, cache deletion, or
additional capture is required for this comparison.

```bash
git pull --ff-only
python3 devtools/pipeline_stability.py start --test wheel-submit
```

Use the same stationary Time Trials antigravity view. Report whether the wheel
illumination is steady, absent, or still flickers, and any performance change.
Then restore before further experiments:

```bash
python3 devtools/pipeline_stability.py restore --test wheel-submit
```

Successful wheel-light collection already restored its original settings. If
collection failed, first restore with `capture_menu.py restore --scene shadows
--shadow-test wheel-light` and the original `--output` if one was specified.
Use a fresh `--output` for a repeated comparison; preserve earlier backups.
A positive result would justify investigating split/depth transitions; a
negative result would leave light inputs, sampling and depth state open.

### Reduced splitting helps, but moving still flickers

The user reports that `wheel-submit` still flickers during movement, less than
before, while stationary flicker is gone. This is a partial improvement, not a
fix. Changing submission timing also changes frame time and potentially dynamic
resolution; the observation alone does not prove a command-buffer defect.
Further comparisons should include both stationary and moving antigravity views.

The next comparison disables Turnip's LRZ optimization directly, while keeping
`DM_VK_CB_DRAWS=0` as in the partial improvement. This differs from FDZ=0, which
only disables the host's fragment-depth shader workaround and does not globally
disable driver LRZ. Normal depth testing remains enabled.

Verified against the bundled Mesa revision `4497ea2a31`:

- [tu_util.cc](https://github.com/chaotic-cx/mesa-mirror/blob/4497ea2a31/src/freedreno/vulkan/tu_util.cc)
  parses `TU_DEBUG` and registers `nolrz`.
- [tu_device.cc](https://github.com/chaotic-cx/mesa-mirror/blob/4497ea2a31/src/freedreno/vulkan/tu_device.cc)
  initializes `device->use_lrz = !TU_DEBUG(NOLRZ)`.
- [tu_lrz.cc](https://github.com/chaotic-cx/mesa-mirror/blob/4497ea2a31/src/freedreno/vulkan/tu_lrz.cc)
  leaves LRZ disabled when `use_lrz` is false. The packaged driver also contains
  the `nolrz` option. The Android host loads arbitrary env.txt keys before Vulkan
  initialization. A full app restart is necessary because Turnip reads debug
  options once.

No APK rebuild or new diagnostic archive is required:

```bash
git pull --ff-only
python3 devtools/pipeline_stability.py start --test wheel-lrz
```

This works whether `wheel-submit` is still armed or has already been restored.
Existing TU_DEBUG flags are preserved and `nolrz` is added once. The helper
backs up the exact current settings and stops the app; reopen it manually.
Compare illumination during both movement and standing still, and note frame
rate changes. Disabled early rejection can increase GPU cost. Report whether
flicker disappears, remains, or the light itself disappears.

```bash
python3 devtools/pipeline_stability.py restore --test wheel-lrz
```

Restoration returns to the settings present before this test. If the earlier
wheel-submit comparison was still active, restore that afterward too, using its
own backup. A successful result would implicate the LRZ path but would still
need a performance assessment and narrower runtime investigation before choosing
a permanent workaround. A negative result would keep changing light inputs,
depth state, sampling and resolution transitions under investigation.


### Motion capture after the LRZ comparison

The user reports that `wheel-lrz` also only partly helps: remaining flicker is
less frequent and occurs mainly during acceleration/deceleration. Neither
comparison establishes LRZ or submission splitting as the root cause. The next
capture observes those transitions rather than adding a rendering workaround.

`--shadow-test wheel-motion` needs the updated runtime. It filters passes by
vertex shader 35696712904ac390, which the existing trace identifies as the local
light-volume shader. Pass selection has no size or pass-number filter, so it
follows dynamic resolution changes. It captures 16 presents, subject to the
existing 96-image cap:

- Both bound colour attachments, with each view's layer (diffuse/specular light
  outputs in the observed pass), as PPM previews and exact packed R11G11B10 `.u32`
  sidecars. Pixel interpretation uses the PPM dimensions and little-endian
  Vulkan B10G11R11_UFLOAT_PACK32 layout.
- The tested D32 attachment, including its existing `.f32` values. The generic
  depth dumper captures layer zero; this observed light depth image has one
  layer. This is not a capture of all sampled G-buffer textures.
- Each matching draw's shader keys, pipeline hash, viewport, dimensions and
  depth/cull/clamp/FDZ state, plus reflected vertex/fragment constant buffers:
  up to 512 bytes each as exact hexadecimal words in the log, bounded to 1024
  draws. The observed light buffers are 224 and 96 bytes and fit this bound.
  These are CPU replay uniform snapshots, not reads of the GPU uniform buffer.
- Final images for presents 9000–9017, bracketing the pass window, plus one full
  frame trace and the capture's settings. Use logged present numbers to align
  the effect images and final frames.

The collector checks that the new runtime accepted the shader filter and that
at least eight presents contain both light targets and depth, with draw/uniform
logs present. It rejects an older APK or incomplete results instead of silently
accepting the earlier exact-size capture. Readbacks and logging change timing;
absence of flicker in this capture does not demonstrate a fix.

Pull the branch, rebuild/reinstall using the existing port command with the same
signing key and Turnip ZIP (`--vulkan-driver`, see [TURNIP_TEST.md](TURNIP_TEST.md)).
No shader translation changes were made. Then:

```bash
python3 devtools/capture_menu.py start --scene shadows --shadow-test wheel-motion
```

Open Time Trials at Mario Kart Stadium and reach the banked antigravity section.
The default present 9000 is roughly five minutes at 30 FPS from launch (longer
if frame rate drops). Around that time, repeatedly accelerate briefly and
release/brake while remaining in antigravity, without pausing. Keep doing this
through the capture window; do not hold the kart stationary throughout. After
about six minutes, or later if capture slowed the game, collect:

```bash
python3 devtools/capture_menu.py collect --scene shadows --shadow-test wheel-motion
```

Send `work/mk8-shadows-wheel-motion-capture/mk8-shadows-wheel-motion-diagnostics.zip`.
If too large to upload, recompress the capture folder as `.7z`. No repeat run
is needed just for compression. A short screen recording of the same remaining
flicker can help if capture timing suppresses it, but is not required to start.
The helper preserves current rendering settings and restores them after
successful collection. If collection fails, retain the folder/log and retry;
restore with the same options and `restore` action if needed. This mode uses a
fresh output directory separate from previous experiments.

Analysis will first check for discontinuities in light transforms/parameters
and resolution while comparing both light outputs against tested depth. A
uniform discontinuity may also be legitimate animation; it requires shader
interpretation and correlation with the visible change. Stable CPU snapshots
alone cannot prove GPU uniform data, synchronization or sampling is correct.

### Motion archive analysis: isolate sampled inputs next

The received `mk8-shadows-wheel-motion-diagnostics.7z` is complete: 16 effect
presents 9000–9015, 48 intermediate images with raw depth/packed colour, and 18
final frames. Its settings use the normal Turnip/CPU BC baseline, with neither
TU_DEBUG=nolrz nor DM_VK_CB_DRAWS=0. It therefore reproduces the baseline issue;
it cannot measure the residual after those comparisons.

The draw/uniform records identify the four nearby cyan wheel lights as fragment
shader **30b45cd2223d3964**, sharing vertex shader 35696712904ac390 with the
13 lights using fragment shader 0722cc0403877a4e. Wheel lights remain submitted
through all 16 captured presents. The wheel shader writes diffuse output zero;
its SPIR-V samples normals at binding 1 and linear depth at binding 2, reconstructs
surface position, and evaluates clamped Lambert lighting and distance falloff.
It has no discard operation. Its uniforms do not simply turn off on dark frames.

A useful pair is effect presents 9012 and 9013 (pass dumps 36–41):

- Both are 579x326, with identical captured camera c0 words and pipeline keys.
- The four wheel lights move at most 0.000245 world units between CPU snapshots;
  radii shrink about 0.305%, and cyan colour strength about 0.301%.
- Summing the exact green component of target zero over x=[230,345), y=[210,275)
  gives 5347.172 versus 912.911, an 82.93% drop. Pixels above green=1 fall from
  1465 to 400. This measures that specific region, not the entire frame.
- D32 differs mostly slightly in this region, with some animated geometry/outlier
  pixels. Among 1382 pixels across the image losing over 90% of green from a
  starting value above 1, median absolute depth change is 2.86e-6. Depth is not
  bit-identical, and sampled linear depth/normals are absent from this archive.
- Vertex and fragment c0/c1 snapshots agree for each draw. These are CPU replay
  snapshots and do not prove the GPU consumed those exact values.

This pair rules out a changing resolution/camera matrix as the immediate cause
of its brightness jump. It does not distinguish incorrect normals/linear depth,
GPU uniform data, rasterization/depth rejection, or a legitimate animated input.
An exploratory ideal-sphere coverage estimate using the captured matrix/depth
allows almost all lost pixels, but it is not a replay of the actual polygon mesh
and cannot establish correct rasterization. No rendering fix is justified yet.

**Frame numbering correction:** texture/effect present N in this runtime maps to
`frame_(N+1).ppm`, since `vk_tex_sweep` advances the texture counter after the
presentation shot. The visible alternation corroborates that mapping in this
archive. Thus effect 9012/9013 compare with final images 9013/9014. Earlier prose
about matching presents must account for this one-frame offset.

#### Capturing sampled normals, linear depth, and volume mesh

The new `wheel-inputs` mode extends `wheel-motion`, without a shader workaround.
It saves the last observed fragment binding 1/2 images at the end of the filtered
pass (the observed light draws share them), with exact raw bytes:

- Vulkan format 64 / A2B10G10R10_UNORM_PACK32: normal `.raw` file, 4 bytes/pixel.
- Vulkan format 76 / R16_SFLOAT: normalized linear-depth `.raw`, 2 bytes/pixel.
- Existing diffuse/specular `.u32`, D32 `.f32`, CPU uniform words and final frames.
- One CPU indexed-draw packet of the shared light-volume mesh, to replace the
  ideal sphere approximation with the actual 864-index geometry.

Input capture supports only single-layer, single-mip base images, as in the
observed pass; sample swizzles and samplers remain described in the full trace.
During this diagnostic only, descriptor memo lookup is bypassed for the selected
vertex shader so bindings are observed even on a reuse hit. Descriptor-set caching
and the actual draw state remain enabled. Readbacks and logging also change timing;
a run without visible flicker is inconclusive. At five images per present,
16 presents use 80 of the existing 96 readback slots, assuming one matching pass.
The collector requires raw inputs of both expected formats across at least eight
presents, plus a complete mesh packet. It rejects the earlier APK's output.

Pull and rebuild/reinstall the APK using the existing port command, same signing
key and Turnip ZIP. Then:

```bash
python3 devtools/capture_menu.py start --scene shadows --shadow-test wheel-inputs
```

Use Stadium Time Trials and the same antigravity location. Around the scheduled
present 9000 (roughly five minutes at 30 FPS from launch), briefly accelerate and
release/brake repeatedly through the window. Do not pause. Collect after about
six minutes, or later if readbacks slow the game:

```bash
python3 devtools/capture_menu.py collect --scene shadows --shadow-test wheel-inputs
```

Send `work/mk8-shadows-wheel-inputs-capture/mk8-shadows-wheel-inputs-diagnostics.zip`,
or recompress the folder as `.7z`. This is a fresh directory, avoiding the old
capture's existing-output error. Settings are preserved and restored on successful
collection; use the same options with `restore` if recovery is needed.

The next offline comparison will evaluate wheel diffuse lighting from the raw
sampled inputs and recorded parameters, then compare actual mesh coverage/depth
if the fragment calculation predicts illumination where the output is dark.
