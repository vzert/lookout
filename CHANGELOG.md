# Changelog

## 0.8.0

- Auto mode: the forced dialog is now opt-in, off by default. lookout adds no dialogs of its own in auto mode; auto
  mode's own classifier decides, as it does without lookout (decision of the user, 2026-10-05: on claude-vzert about 4 of
  every 14 dialogs came from lookout, mostly reads with variables). Turn it on with `dialogo_forzado = true` in
  `~/.config/lookout/permisos.toml`; its rules and the CI check against 0.7.1 are unchanged. `lookout permisos` says
  whether it is on. Push governance (`lookout gobierno`, `publica`, `regla-push`) does not depend on it.

## 0.7.3

- Fix: `lookout gobierno` crashed with `KeyError: 'tareas'`. The stuck-agent counters (Fase 6) were written to the same
  `counters.json` as the adversary-round counters of each task, and replaced the whole file. They now live in
  `atascado.json`. An older `counters.json` without `tareas` is read and repaired. A round limit the user raised before
  the overwrite is lost: raise it again with `lookout gobierno … --usuario-amplia`.

## 0.7.2

- Agents are named to the user by their herdr **tab**, the one thing the user sees: `resumen`, events, herdr
  notifications and permission notices say `Cambio DeepSeek (cambio-deepseek)`, never a pane id.
- A new agent in a tab the user named takes its name from that label (`Cambio DeepSeek` → `cambio-deepseek`), checked
  against every herdr agent name. Registered agents keep their name.
- `lookout entrega` puts the agent's name on its tab when the tab still has herdr's default label (its number) and holds
  only that pane. A label the user chose is never changed. `lookout lanza` names the new agent's tab too (herdr's
  `--label` names its workspace; the tab was left as "1").
- `supervisor.md` (what a relief supervisor reads) lists agents by tab and name, without pane ids.
- `lookout inicia` names the supervisor's own tab «Supervisor» (same rule: default label, one pane) and renames its
  session to `supervisor-<repo>` (applied when the turn ends; skipped if the input box has text).
- Supervisor budget counts from what its session already held at `lookout inicia` (+300k); it was a fixed 120k, and a
  supervisor that started at 71k had to hand over after 7 minutes. `LOOKOUT_PRESUPUESTO` still sets the whole limit.
- Relief: the supervisor keeps watching (and relaunching its waiter) until the new one takes the lock, and the user gets
  a herdr notification. Before, it stopped its waiter and the project went unwatched until the user acted. It hands
  over only on `PRESUPUESTO SUPERADO`.
- Auto mode: fewer forced dialogs on reads. Words of a reserved command must stand alone: "push" inside a file name
  (`git add bin/checkpoint-push.sh`) is no longer a push; `/usr/bin/git push` still is. A variable after git/gh/npm
  still gets the dialog, as in 0.7.1, reads included (`gh pr view $n`): every exception for it was a hole.
- Auto mode: `gh repo delete`, `gh repo archive` and `gh api` that writes (`-X POST|PUT|PATCH|DELETE`, or fields, except
  a graphql query without `mutation`) now get the dialog too.
- Auto mode also forces the dialog for: the command inside `sh -c`/`bash -c`, `xargs` into rm/rmdir/mv/git/gh/npm,
  `find -delete`/`-exec rm` outside the worktree, a script piped into a shell (`| bash`), `gh${IFS}api`, git aliases
  built at run time (`git -c alias.x=$C`), `gh api -X $M`, `gh api --input`, glued fields (`-Fname=x`), and `gh`
  global options before `api` (`gh -R o/r api -X DELETE`).
- The forced dialog reads the command text: it is a tripwire for the usual forms, not a boundary. A command built in
  ways the text does not show (`D=rm; $D /x`, `sh script.sh`, `git -c alias.x='!rm /x'`, `| env bash`) can pass it.
  Auto mode's own classifier still judges every command.
- CI checks that the forced dialog is never weaker than 0.7.1 (`tests/test_lookout_diferencial.py`: 126,162
  generated commands against the frozen 0.7.1 code, no exception).
- Known limit: "git push" written as text inside quotes or a heredoc (a grep pattern, a commit message) still gets the
  dialog; telling text from `sh -c 'git push'` is not safe from the command text alone.
- README: start the supervisor inside the project with `/lookout:supervisa .` (no path to type), plus a short guide
  to what happens next and the messages you can see.

## 0.7.1

- CI: `actions/checkout@v5` (Node 24). v4 runs on Node 20, which GitHub deprecated.

## 0.7.0 — first public release

- Own marketplace: `lookout@lookout-marketplace` (repo `vzert/lookout`).
- `lookout inicia` checks herdr before taking the project lock: `herdr --version` at least 0.9.1, `herdr status`
  server running and compatible with the client. Otherwise `NO ARRANCO` (exit 6) and nothing is taken.
- Without goalspec: a warning at start; `lookout gobierno` says `SIN-GOALSPEC` and the push goes to the user marked as
  not reviewed; task prompts leave out the goalspec rules.
- Transcripts and the 3-tier plugin are looked up under `CLAUDE_CONFIG_DIR` when it is set.
- CI on Ubuntu and macOS (`tools/run-tests.sh`): shell syntax, Python compiles, manifests and the version rule
  (plugin.json == marketplace.json `metadata.version`), skill frontmatter, unit suite.
- Includes everything built before: supervising live agents (0.1), batches of pendientes in worktrees (0.2), goalspec
  governance and ordered publishing (0.3), supervisor relief (0.4), tool permissions by user rules (0.5), stuck-agent
  heuristics and dev-server ports per worktree (0.6).
