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
