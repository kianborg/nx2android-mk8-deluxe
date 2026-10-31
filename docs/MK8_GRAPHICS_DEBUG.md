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
| Mesa Turnip | No custom-driver loader integrated | A useful future driver comparison for this Adreno; requires Android driver-loading integration and device verification |
| OpenGL ES | No Android NVN backend implemented | A new backend, not a selectable setting |
| Metal | Apple backend only | Cannot run on this Android phone |

Turnip changes the Vulkan driver, not the NVN rendering backend. The runtime
currently opens system `libvulkan.so` directly. Renaming a downloaded driver
library is not a supported installation method.

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
