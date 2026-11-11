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
| MK8 CPU BC Test | PR #140 at `308a672` | `org.nx2a.t0100152000022000.prtest.cpubc` |
| MK8 CPU BC Baseline | Upstream `5e4ea3b`, the PR's rebase base | `org.nx2a.t0100152000022000.prtest.cpubaseline` |

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

These build the same two separate test apps listed above. They pin the published PR at `308a672` and its unchanged upstream base at `5e4ea3b`, so the comparison isolates the PR. They do not build the full fork or silently change PR source to a newer upstream revision. PR #140 was separately integration-tested against upstream `d4bccf0`; that check did not update the published PR branch.

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
