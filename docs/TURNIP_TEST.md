# Optional Turnip driver comparison

This is an experimental per-app Vulkan driver comparison, not a new NVN
renderer. It resolved the reported graphics corruption in the device test below. Android's system driver remains the
default. No root, system driver replacement or uninstall is needed.

## Verified device result (2026-10-31)

The user tested Nothing Phone (1), Android 15, Adreno 642L, with Mario Kart 8
Deluxe 4.0.0 and KIMCHI's Mesa Turnip revision 9v2. The supplied log confirms
Mesa 24.3.0-devel (git-4497ea2a31), Vulkan 1.3.296 and driverID 18, with no
`[RED]` entries. Turnip reports the device name as Adreno 7c+ Gen 3.

The supplied screenshots show the title and main menus, character roster,
Mario in kart selection, vehicle parts, cup previews and Stadium rendering.
Mario and the race HUD are visible, and the large coloured rectangles seen
with the Qualcomm driver are absent in the supplied Stadium screenshot.
Its counter shows 30 FPS; this short run does not establish sustained frame
rate or compatibility across every circuit. The comparison demonstrates a
working driver-dependent workaround with the current runtime, without
identifying the exact defect inside the Qualcomm driver.

Keep `DM_VK_DRIVER=turnip` and `DM_VK_BC_DECODE=1`. The successful comparison
also used `DM_VK_NOPCACHE=1`; that diagnostic setting can be removed to allow
pipeline caching after backing up the working env.txt. Restoring the original
pre-probe settings also disables Turnip and returns to the failing system path.

The maintainer's release page is:
https://github.com/K11MCH1/AdrenoToolsDrivers/releases/tag/v24.3.0_r9

## Build the optional APK

Download the binary driver ZIP, not GitHub's source archive:

```bash
curl -fL https://github.com/K11MCH1/AdrenoToolsDrivers/releases/download/v24.3.0_r9/turnip_v24.3.0_R9v2.zip \
  -o "$HOME/Downloads/turnip_v24.3.0_R9v2.zip"
```

Update the fork source, then add this argument to the usual port command:

```bash
--vulkan-driver "$HOME/Downloads/turnip_v24.3.0_R9v2.zip"
```

The porter checks the ZIP's ARM64 ELF libraries, builds the pinned BSD-licensed
AdrenoTools helpers with the NDK, and packages them and license/metadata assets
in the APK. No CMake or extra system installation is required. The primary
library is packaged as `libnx2a_turnip.so` because Android extracts native APK
libraries with lib*.so names; ZIP metadata can name it `vulkan.ad07xx.so`.
Install the APK normally over the existing installation using the same signing
key. The system Vulkan path is still selected until env.txt explicitly opts in.
This option is currently available through the CLI, not a GUI driver picker.

## Run the comparison

To reproduce the comparison from the original settings backup (this replaces
env.txt; preserve any newer settings first):

```bash
PKG=org.nx2a.t0100152000022000
DATA=/sdcard/Android/data/$PKG/files
adb shell am force-stop "$PKG"
adb push mk8-env-before-depth-probe.txt "$DATA/env.txt"
adb shell "printf '\nDM_VK_DRIVER=turnip\nDM_VK_BC_DECODE=1\nDM_VK_NOPCACHE=1\n' >> '$DATA/env.txt'"
```

The forced CPU BC decode retains the current texture path for this comparison:
Turnip can advertise native BC, but this runtime's generated-BC shadow path is
currently for CPU-decoded textures. Starting an empty Vulkan cache avoids
mixing driver cache data. Leave prior draw probes, copied-pool and other A/B
switches disabled. Open the game, first check Mario in character selection,
then briefly check Stadium if it boots and renders.

```bash
adb exec-out screencap -p > mk8-turnip.png
adb pull "$DATA/log.txt" mk8-turnip-log.txt
```

The log must report `custom driver identity` with driverID 18 (Mesa Turnip).
The runtime refuses an unverified custom driver or a silent system fallback.
A failed custom-driver launch is also useful evidence: retrieve log.txt before
relaunching. The integration is cross-compiled and tested with mocked loader
routing and real ZIP/APK packaging, and the device result above confirms loading
and rendering on the tested phone.

## Restore the system driver

```bash
adb shell am force-stop "$PKG"
adb push mk8-env-before-depth-probe.txt "$DATA/env.txt"
```

Removing DM_VK_DRIVER, or setting it to `system`, restores system Vulkan at the
next launch. The optional libraries remain inactive in the APK. Saves and the
game's data pack are not modified by selecting the driver.
