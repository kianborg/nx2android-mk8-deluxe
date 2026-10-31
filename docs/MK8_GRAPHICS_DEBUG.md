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
