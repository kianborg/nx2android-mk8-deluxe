# Rules for Claude in this repository

The skills in `.claude/skills/` (nx2android-dev, switch-android-port) hold the full guide. These rules hold in every session, with or without a skill.

## Game files go only in `.gamedump/`

- Every port, test, check or bundle trial uses `.gamedump/<App>/` in the main checkout (git-ignored; `<App>` is the APK's name, e.g. `HadesII`), also from a worktree. Never make a game, bundle or player folder elsewhere on the PC: `C:\nx2a-test` once kept 263 GB that nobody deleted.
- Fill it with hard links to the downloaded NSP / NSZ / XCI files (`ln`, same drive, no copy). Never write into the download folders; porter decompresses NSZ and XCZ itself.
- Delete `.gamedump/<App>/` when the work is done (port committed, test app uninstalled). First check that each dump file has 2 or more links (`fsutil hardlink list <file>`); a file with one link is the only copy, so ask first. The PC has little disk space.
- Before ending a session that made a `.gamedump` folder, say which folders are left and why.
