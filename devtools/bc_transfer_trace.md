This is a diagnostic build for investigating PR #140. The helper downloads PR
commit `6eb7bcb`, then adds recording/replay trace code only to that temporary
source tree. The trace is not part of the PR. It uses the existing separate
CPU BC test package; the working game app is unchanged. The build receipt
records trace revision `v1` and the native library hash.

Update both helpers in your existing project folder:

```bash
curl -fL https://raw.githubusercontent.com/kianborg/nx2android-mk8-deluxe/devtools/mk8-cpu-bc-comparison/devtools/build_install_mk8_pr.py -o devtools/build_install_mk8_pr.py
curl -fL https://raw.githubusercontent.com/kianborg/nx2android-mk8-deluxe/devtools/mk8-cpu-bc-comparison/devtools/collect_mk8_bc_logs.py -o devtools/collect_mk8_bc_logs.py
```

For the Nothing Phone (1), build the Odyssey test with Turnip and CPU BC forced:

```bash
.venv-pr/bin/python devtools/build_install_mk8_pr.py --game odyssey --game-folder /home/kianpc/SMO --cpu-bc --trace-transfers
```

Open **Odyssey CPU BC Test** after the helper finishes. GPU snapshots are off
for this first run. Reach the first playable section after the intro, play for
about 30 seconds, then collect while the app is still open:

```bash
.venv-pr/bin/python devtools/collect_mk8_bc_logs.py --game odyssey
```

Send the printed ZIP path's archive. Do not change readback mode during this
capture. Record the scene reached. There is no need to rebuild the baseline app
for this initial request trace. The same helper supports `--game 3dworld
--game-folder /home/kianpc/SM3DW` if a later investigation needs it.

`BC transfer trace v1: record b2t` reports requested destination formats and
regions. `replay b2t` reports entry, lookup/validation failures, a CPU upload,
an upload supplied by a GPU snapshot, or a native-format upload. Both the
texture format and an explicitly requested view format are logged. Messages
are sampled separately by format and outcome: the first three, then powers of
two. No texture bytes are logged.

At frame zero and every 300 rendered frames, `summary` reports cumulative
recorded/replayed copies, those with BC destination formats, completed CPU/native
upload recording, and skipped copies. This proves tracing is active even when
there are no requests. Counts can differ because recorded lists can be reused,
left unsubmitted, or replayed asynchronously. A summary covers its reporting
point, not necessarily the end of the capture. `transfer-trace.json` summarizes
only the current `log.txt` and preserves that distinction.

Upload events mean the image copy was recorded in a command buffer; they do not
prove GPU completion. A `gpu-snapshot-upload` plus the existing snapshot
completion message provides stronger path evidence. A missing trace marker or
summary does not mean zero requests. Successful software Vulkan fixture checks
do not qualify physical Mali or Adreno behavior.

To change GPU readback later, use the exact `--configure-only` command printed
by the helper, with the real work folder it created. Trace mode is preserved.
Receipts for older or uninstrumented builds cannot enable this trace without a
rebuild. Omitting `--trace-transfers` on a fresh build produces the unchanged PR
runtime with tracing off.

For the original Hollow Knight, use `--game hollow-knight` in both helpers.
This means title `0100633007D48000`, not Hollow Knight: Silksong. The pinned
source has no profile for the original game: `porter --experimental` will
attempt to generate one from your files. Its ability to build or start is
unverified; a startup failure alone does not identify a PR #140 regression.
No provisional game profile or extracted game data is added to this repository.

```bash
read -r -p "Enter your original Hollow Knight game-folder path: " hk_game_folder
.venv-pr/bin/python devtools/build_install_mk8_pr.py --game hollow-knight --game-folder "$hk_game_folder" --cpu-bc --trace-transfers
```

If the build succeeds, open **Hollow Knight CPU BC Test**, start or load a game,
play for about 30 seconds after gaining control, then collect with:

```bash
.venv-pr/bin/python devtools/collect_mk8_bc_logs.py --game hollow-knight
```

GPU snapshots stay off for the initial trace. The installed title and version
are verified and collected from the actual data manifest. Using BC textures
does not by itself establish that the game uses the BC buffer-copy path.
