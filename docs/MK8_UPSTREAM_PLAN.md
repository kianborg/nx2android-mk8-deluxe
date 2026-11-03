# Upstreaming the working Mario Kart 8 Deluxe setup

The goal is to upstream the complete set of useful changes that made MK8
playable, through focused pull requests. The existing alias-fix branch is the
first contribution, not the whole MK8 port.

On 2026-11-03 the reporter confirmed that the full fork still renders a race
correctly after merging upstream through `3d98ec0`. This includes the flicker
fix. Tested setup: Nothing Phone (1), Android 15, Adreno 642L, Turnip R9v2,
forced CPU BC decoding. This is one device and a short race test, not coverage
of all tracks, devices or sustained performance. Earlier intermittent crashes
have not been established as resolved.

## Proposed review order

| PR | Scope and original commits | Dependencies / preparation |
| --- | --- | --- |
| 1 | Inactive identical-view colour attachment aliases (`d5eb2ff`; clean branch commit `8ba0e6a`) | Already isolated on `fix/inactive-colour-attachment-aliases`, directly based on upstream. Two files; 54 tests pass and Android release host builds. |
| 2 | RGB565 packed channel order (`960fbbc`) | Independent format-table correction; extract its regression into an upstream-compatible test rather than importing the entire fork BC upload fixture. Fixes blue cup/menu colours. |
| 3 | Texture view selectors override parent selectors (`18886dd`) | Isolate sampling semantics and test; separate diagnostic description helpers from the required runtime change. Fixes antigravity shadows. Check against upstream texture/view code. |
| 4 | CPU BC texture fallback and GPU-generated BC targets (`48bdd62`, `0bed069`, `53549c7`, relevant follow-ups) | Larger prerequisite for this phone's working configuration. Include decoder/layout/upload tests, synchronous GPU snapshot handling, async-pipeline readback ordering, integer target shader variants, install defaults and documentation. Split base decode and generated-target support further if useful, with explicit dependency. Review the final diff against upstream because some BC handling already exists there. |
| 5 | Optional packaged Turnip driver (`c17bdb7`) | Porter option, ZIP validation, loader selection/identity verification, pinned AdrenoTools integration, notices, tests and user instructions. Can be reviewed independently; reproducing the known MK8 setup also requires the CPU BC work. System driver stays the default; player supplies a driver ZIP. |
| 6 | Vulkan portability fixes (`748eb6c`, `d7bbc26`, related shader variant changes) | Separate depth-clip fallback from integer vertex-register preservation. Reconcile integer variants with PR 4. Cross-compile and test independently; the successful Turnip run does not prove that every fallback is required on Turnip or fixes the Qualcomm driver. |
| 7 | Shader translation progress/stall reporting (`f7ce3f0`) | Independent build usability change, with worker and progress tests. Can be submitted in parallel with renderer work. |
| 8 | Reusable diagnostics and player instructions | Review capture/readback/draw packet code and tools separately after production fixes. Keep runtime diagnostics opt-in. Publish a concise MK8 setup guide covering the complete merged dependency set. Generalize personal build paths and fork-specific source download URLs before offering the build/install helper upstream. |

These are review units, not a promise that exactly eight PRs are sufficient.
PR 4 and PR 6 each contain separable changes. Small independent fixes can be
submitted together in time, but should retain separate branches and reviews.

## Submission checklist

- Build each branch from current upstream or explicitly identify its prerequisite
  branch. Do not submit all fork commits as one PR or assume historical commits
  cherry-pick cleanly onto current main.
- Carry the regression test with each runtime change. Run the applicable upstream
  suite and Android host build on the isolated branch, and record those results.
- Describe the concrete fault, resulting behavior and device evidence. Distinguish
  device testing of the combined fork from isolated-branch host verification.
- Keep the working full fork available while the series is reviewed. After
  upstream merges and conflict resolution, retest the combined configuration.
- Include required third-party attribution. Review the changed bcdec notice and
  AdrenoTools pin/licenses; do not ship game assets, keys, captured game shaders,
  APKs or the reporter's logs in source PRs.
- Preserve useful diagnostics in their own contribution rather than including the
  1,299-line investigation diary and obsolete A/B settings in every renderer PR.
- Offer a short before/after clip and the exact tested device/driver settings.
  Avoid claiming universal MK8 compatibility or that the random crash is fixed.

## Current state

No pull requests have been opened by this preparation work. PR 1 is pushed and
ready for submission. PRs 2 onward are identified from the full fork diff; they
still need clean branches, dependency review and branch-specific validation.
The full fork's last verification passed 137 tests (three optional analysis
skips) and compiled the 142-source Android release host. Its post-sync race
test was supplied by the reporter.
