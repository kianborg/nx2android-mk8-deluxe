# MK8 CPU BC comparison helper

This fork-only development branch hosts the APK testing helper. The helper downloads pinned source revisions; renderer changes on this branch do not enter the test APKs.

From your existing PC source folder, refresh the helper without needing a Git checkout:

```bash
curl -fL https://raw.githubusercontent.com/kianborg/nx2android-mk8-deluxe/devtools/mk8-cpu-bc-comparison/devtools/build_install_mk8_pr.py -o devtools/build_install_mk8_pr.py
```

Use the existing Python environment, game folder, keys, Turnip ZIP and connected phone. Default paths match the current MK8 setup; see `--help` for overrides.

Build and install the PR app with forced CPU BC decoding and GPU readback off:

```bash
.venv-pr/bin/python devtools/build_install_mk8_pr.py --cpu-bc
```

Build and install unchanged upstream with forced CPU BC decoding:

```bash
.venv-pr/bin/python devtools/build_install_mk8_pr.py --upstream-baseline
```

| App | Source | Package |
| --- | --- | --- |
| MK8 CPU BC Test | PR #140 at `4c5a419` | `org.nx2a.t0100152000022000.prtest.cpubc` |
| MK8 CPU BC Baseline | Upstream `e5a4703`, the PR's rebase base | `org.nx2a.t0100152000022000.prtest.cpubaseline` |

Each has separate saves and settings. Both bundle the selected Turnip driver and start with GPU readback off. The existing working game and MK8 PR Test use different package IDs. Rebuilding one comparison app updates that app.

Compare the same race, kart, scene and handheld/docked setting in both apps. Allow pipeline warmup to settle before comparing performance. Preserve screenshots of artifacts, logs and the printed work-folder paths. An upstream comparison helps distinguish existing CPU fallback problems from regressions in the PR.

To enable ordered snapshots in the PR CPU app without rebuilding, replace the example path with that app's printed work folder:

```bash
.venv-pr/bin/python devtools/build_install_mk8_pr.py --configure-only /actual/pr/work/folder --gpu-readback
```

Omit `--gpu-readback` to turn snapshots off again; CPU decoding stays enabled. The helper stops the selected app before changing settings, so reopen it after configuration. The upstream baseline rejects the PR-only readback option. Old receipts or different installed runtimes are refused rather than silently reconfigured.

A successful snapshot logs `BC GPU snapshot: ordered readback completed`. Enabling a setting does not prove that the tested workload reached the path. Forced CPU decoding on Adreno 642L is useful functional coverage, but does not establish behavior on Mali or Adreno 619.

## Lenovo Idea Tab 5G: stock Vulkan testing

Use `--lenovo` for the Lenovo Idea Tab 5G. This uses the system Vulkan driver, requires no Turnip ZIP, and sets `DM_VK_X_BC_CPU=0` so the driver capabilities choose the fallback naturally. It removes any old `DM_VK_DRIVER` override from the selected test app's settings. It does not change the existing working app.

Connect the Lenovo with USB debugging enabled. Disconnect other devices or add `--device SERIAL` (find it with `adb devices`). Use your existing PC game folder, keys and Python environment.

```bash
curl -fL https://raw.githubusercontent.com/kianborg/nx2android-mk8-deluxe/devtools/mk8-cpu-bc-comparison/devtools/build_install_mk8_pr.py -o devtools/build_install_mk8_pr.py
.venv-pr/bin/python devtools/build_install_mk8_pr.py --lenovo
.venv-pr/bin/python devtools/build_install_mk8_pr.py --lenovo --upstream-baseline
```

These build the same two separate test apps listed above. They pin the published PR at `4c5a419` and its unchanged upstream base at `e5a4703`, so the comparison isolates the PR. They do not build the full fork or silently change PR source to a newer upstream revision. PR #140 was separately integration-tested against upstream `d4bccf0`; that check did not update the published PR branch.

First compare the same scene with readback off in both apps. Check the runtime log for `BC no (decoded on the CPU)` to establish that this is natural fallback coverage. `BC yes` means the device's current driver supports native BC; report that rather than claiming a CPU-only device test. An artifact, crash or slow frame rate alone does not identify a PR regression.

Then enable snapshots only in the PR app using its printed work folder:

```bash
.venv-pr/bin/python devtools/build_install_mk8_pr.py --configure-only /actual/pr/work/folder --gpu-readback
```

The receipt preserves system-driver and automatic-BC selection without repeating `--lenovo`. Reopen the app after each settings change. Preserve each run's log before restarting again; the runtime keeps only its current and previous startup logs. A successful snapshot logs `BC GPU snapshot: ordered readback completed`; an enabled switch without that line does not confirm execution.

Download and run the read-only collector while the tested app is running:

```bash
curl -fL https://raw.githubusercontent.com/kianborg/nx2android-mk8-deluxe/devtools/mk8-cpu-bc-comparison/devtools/collect_mk8_bc_logs.py -o devtools/collect_mk8_bc_logs.py
.venv-pr/bin/python devtools/collect_mk8_bc_logs.py
```

Upload the printed ZIP and screenshots of the artifacts, noting which app and readback setting produced each. With multiple devices connected, pass `--device SERIAL` to the collector too. It gathers available MK8 logs/settings and PR host marker metadata; it makes no phone settings changes, installs nothing, and retains no inspected APK.

## Lenovo black-screen clip-depth experiment

The captured Mali driver reports no depth-clip-control extension. The published isolated runtime does not convert the GL clip-depth range on that path. `--clip-depth-test` adds the fork's existing runtime conversion to both pinned sources, without adding it to PR #140. The Lenovo device comparison restored the picture in both apps and logged the conversion; other drivers and scenes remain unverified.

Refresh both scripts from this branch using the download commands above, then run:

```bash
.venv-pr/bin/python devtools/build_install_mk8_pr.py --clip-depth-test
.venv-pr/bin/python devtools/build_install_mk8_pr.py --clip-depth-test --upstream-baseline
```

This mode implies `--lenovo`. It creates **MK8 Clip PR** (`org.nx2a.t0100152000022000.prtest.cpubc.clipdepth`) and **MK8 Clip Base** (`org.nx2a.t0100152000022000.prtest.cpubaseline.clipdepth`). They coexist with the prior apps and use separate saves. System Vulkan and automatic BC selection remain enabled; Both diagnostic builds start with GPU readback off. After verifying the picture, the PR app can switch readback using its verified build receipt; the upstream baseline continues to reject the PR-only readback option.

The pinned base and PR commits remain e5a4703 and 4c5a419. The helper adds the same stage-selective conversion to each downloaded tree: vertex output, or geometry output when present, converts `z` to `(z+w)/2` before clipping. Zero-to-one depth, raster discard, fragment stages and devices with native depth-clip control retain their existing path. Required conversion failures stop rather than silently continuing with the original module. Variant caching distinguishes converted modules. Shader bundles are unchanged.

The conversion's C/header files come from fork commit 5134759 with SHA-256 checks, and the build receipt records that revision. The helper rejects unexpected source layouts and checks the resulting APK for the conversion marker before installing. It edits only a fresh downloaded build folder.

Launch each **Clip** app, allow up to roughly a minute for startup given the recorded copied-pool stalls, and report whether any menus or logo appear. Do not judge performance from this experiment: the expensive copied-pool path is unchanged. Collect a ZIP immediately after each run using `collect_mk8_bc_logs.py`. Look for `GL clip depth remapped to Vulkan` to confirm the conversion was exercised. Include a screenshot if the picture changes. If it stays black, the frame images and pass-level state need investigation next; missing depth-clip control alone does not prove the cause.


### Readback-on follow-up after picture verification

Refresh the helper, then use the work folder printed when **MK8 Clip PR** was built:

```bash
.venv-pr/bin/python devtools/build_install_mk8_pr.py --configure-only /actual/clip-pr/work/folder --gpu-readback
```

Do not pass `--clip-depth-test` again: the existing diagnostic is identified from the receipt. This action verifies the source revision, clip-conversion revision, device, installed host hash and conversion marker before stopping the app and changing settings. It preserves the system driver and automatic BC selection, and does not rebuild or reinstall. Reopen MK8 Clip PR and repeat the same scene, then collect logs immediately. Omit `--gpu-readback` in the configure command to return to off. The Clip Base app rejects readback-on.

The runtime's `BC GPU snapshot: ordered readback completed` line is needed to establish that a successful snapshot occurred. If it is absent, report the test as readback enabled but path execution unconfirmed, regardless of whether the picture is visible.


## Nothing Phone (1): reviewer artifact comparison

The current helper pins the published PR review fixes at 4c5a419 and unchanged upstream at e5a4703. Download the helper again before testing. Older build receipts require rebuilding; do not reuse a Lenovo receipt or a previous PR runtime for this comparison.

Connect only the Nothing Phone (or select its serial with `--device`). Build these without `--lenovo` or `--clip-depth-test`:

```bash
.venv-pr/bin/python devtools/build_install_mk8_pr.py --cpu-bc
.venv-pr/bin/python devtools/build_install_mk8_pr.py --upstream-baseline
```

Both use the same selected Turnip ZIP, force CPU BC decoding and start with GPU readback off. The two separate package IDs preserve the working game. Repeat the exact scene where the earlier visual artifacts appeared, using the same kart, camera and handheld/docked setting. Let pipeline warmup settle before comparing. Collect logs immediately after each run and take matching screenshots of the artifacts if present. Report whether they occur in both, only one, or neither. Native BC support on the phone does not invalidate this comparison because CPU fallback is explicitly forced.

Leave GPU readback off until this comparison is complete: this check answers the reviewer's default-path regression question, not the separate ordered-snapshot coverage question.


## Find a real BC buffer-upload reproducer: Odyssey / 3D World

The PR source is pinned to `4c5a419`, which adds a one-time successful-upload diagnostic and restores `DM_VK_WATCH`. These probes use the published PR unchanged, not an injected upload or a game-specific workaround. A diagnostic marker is checked in the built host before installation. The selected game's title ID is verified in the data-pack manifest before installation; a wrong game folder is refused.

Use the Nothing Phone, the same Turnip ZIP and forced CPU BC. First test the PR with readback **off**:

```bash
.venv-pr/bin/python devtools/build_install_mk8_pr.py --game odyssey --game-folder /actual/odyssey/folder --cpu-bc
```

This installs **Odyssey CPU BC Test**, package `org.nx2a.t0100000000010000.prtest.cpubc`, separately from a normal Odyssey install. Save its printed work-folder path. Test version 1.4.1: cold-start to the title screen and enter the first playable area or load your test save. Record what you did; these are candidate scenes, not yet confirmed reproducers. Immediately collect:

```bash
.venv-pr/bin/python devtools/collect_mk8_bc_logs.py --game odyssey
```

The collector includes the data-pack version metadata. Look for `BC CPU buffer upload: NVN format ..., WxHxD, GPU readback no`. Only a real runtime success line proves this branch executed. Native compressed support alone, BC texture format announcements, a working picture or a CopyBufferToTexture counter without its BC format are insufficient. If the line is absent, do not offer that scene as the maintainer's reproducer.

The second candidate is 3D World + Bowser's Fury 1.2.2:

```bash
.venv-pr/bin/python devtools/build_install_mk8_pr.py --game 3dworld --game-folder /actual/3dworld/folder --cpu-bc
.venv-pr/bin/python devtools/collect_mk8_bc_logs.py --game 3dworld
```

It installs **3D World CPU BC Test**, package `org.nx2a.t010028600EBDA000.prtest.cpubc`. Try startup, the mode-selection menu, and a first level in either mode while recording the tested sequence. No scene is yet verified to exercise the branch.

After a positive marker, build that game's upstream comparison by adding `--upstream-baseline`; this has its own `.prtest.cpubaseline` identity and source pinned to `e5a4703`. The upstream base does not contain the new success log. Compare the exact scene, frames and RED diagnostics with CPU BC forced in both. You can separately opt into readback on the PR app using `--game odyssey --configure-only /actual/pr/work/folder --gpu-readback` (or `--game 3dworld`). Receipts and installed runtime hashes are verified first. Do not mix games' build receipts.

Always refresh both helper and collector from this branch. `--game` defaults to MK8 for existing users; do not omit it for these two games. Other-game probes currently target the Nothing/Turnip workflow and reject `--lenovo`/`--clip-depth-test` to avoid accidentally applying MK8-specific diagnostic setup. No game assets or keys should be uploaded.
