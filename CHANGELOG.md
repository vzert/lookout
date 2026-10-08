# Changelog

## 0.10.0

The rest of the first real session's lessons (docs/plan.md, Fase 9 F), and lookout no longer judging the adversary.

- **Behavior change:** `lookout gobierno` (push) no longer judges the adversary. It needs only the agent's last quoted
  verdict to be `hold`; the `MISMO-MODELO` refusal (a hold from the agent's own model) is gone. Which model and which
  backends a round needs is goalspec's policy, and goalspec applies it in the agent's own session (decision of the
  user, 2026-10-07: lookout coordinates and supervises, goalspec owns the adversary rules, so they are kept in one
  place). **Accepted risk until goalspec enforces it:** a hold from the agent's own model passes to `lookout publica`.
  The gap and the rules lookout dropped were proposed to goalspec, for it to measure and decide. What lookout keeps is coordination: the
  round count per task with the user's yes at the cap, the publication queue, and the user's yes before any push.
  The task prompt now points at goalspec for the rounds instead of restating them.
- The batch cap counts every live session of the project, also the user's own agents that were already running (on
  claude-vzert there were 10 sessions with a cap of 3). The supervisor is not counted; the proposal says how many slots
  they hold.
- The supervisor asks the user in the chat, not with a modal `AskUserQuestion`, while agents are alive (the modal left
  it blocked, and an agent finished unseen): `lookout decision --abre`, the question in the chat, and the turn ends with
  the waiter alive. The user's answer, typed as the next prompt of the supervisor's session, is written on the most
  recent open decision by the hook (a peer's message, a waiter's notification or a `/rename` lookout typed are not
  answers). It authorizes nothing by itself: only `decision --cierra … --si` does.
- `lookout entrega` types the report note only after the agent's `/rename` landed. If it did not and the input box is
  not empty, the note is not typed (exit 4) instead of arriving glued to the `/rename` as pasted text. The note's own
  hook confirmation no longer accepts the `/rename`'s event.
- `lookout libera` prints the exact cleanup of the agent's worktree and branch for the user to run once the pendiente
  is closed (`git worktree remove`, `git branch -d`, never `-D`). lookout itself still removes nothing.
- A launched agent's herdr tab gets a short readable title from the pendiente («Rotar o confirmar el token…»), not the
  truncated slug. The slug stays the agent's name: `lookout` commands still find it by that name, and messages name
  it as «<tab> (<name>)».
- The task asks the agent to send each decision it needs to the supervisor as soon as it exists, not only in the final
  report (two decisions waited 13 minutes inside a report).
- The supervisor skill: it does not read other plugins' reports or code on its own (goalspec's payloads, its
  adversary's transcripts, the plugin cache); it asks the agent for the datum. The round cap, the stuck-agent stop and
  the close also send the supervisor to ask in the chat, not to the modal.
- Tests: the stuck-agent tests (`test_lookout_f6.py`) defined their own `fail()`, which hid unittest's: no assertion in
  them could fail. Renamed; it uncovered that a correction or a `repite` kept in memory had no hour (`ultimo: 0` in the
  live counters; the file had it), now fixed, and a test that stopped a process with signal 19, which is SIGCONT on
  macOS.

## 0.9.0

What the first real session taught (claude-vzert, 2026-10-06; docs/plan.md, Fase 9).

- **Breaking:** `lookout libera <proyecto> <agente>` now requires `--fuera ninguno`, or `--fuera "<what went outside the
  task>" --usuario-confirmo <decision id>`. Without it, it refuses and names the task file to compare the agent's report
  against. On claude-vzert a "measure only" agent copied files to the user's VPS and removed them there, and the slot
  was freed without the user hearing of it.
- Every task carries a fixed rule: write nothing outside the worktree, nor on remote hosts or their `/tmp`; measure a
  remote host with `ssh host 'bash -s' < script`, copying nothing.
- Investigation, message and credential tasks run without a worktree and without edit tools, and no longer in plan
  mode: in plan mode a measuring agent would not even try a read-only `ssh`, and only the user's Shift+Tab could unblock
  it. **Accepted risk (decision of the user):** such an agent keeps Bash. A write by Bash is stopped only by the task's
  rule, the user's own permission rules, and `libera --fuera`, which comes after the fact.
- The batch classifier reads the item without markdown (`**Medir** …` was typed as code), knows `comunicacion` (the
  agent drafts, never sends) and `credencial` (rotate or revoke; high risk; the user acts), keeps a fix as code even if it
  names a token, does not take git refs (`origin/develop`) or generic files (`_pendientes.md`, `CLAUDE.md`) as coupling
  files, and orders the batch by priority and, within it, newest first (inside a coupled pair, the older one first).
- «Memoria relevante» in a task: at most 3 related items, no matches through generic files, texts cut to 300 chars
  (one task weighed 18 KB and handed another agent where a certificate and its password live). Port and database only
  for code tasks. A task draft written by an older template is rewritten.
- The batch proposal says what each agent will do, taken from its task file (`hará:`), in every batch.
- Closing: `lookout descarta` closes, through the journal and with the user's yes, a pendiente that never had an agent;
  `lookout cierra --estado abandoned|superseded` needs no adversary hold and no push. The supervisor never runs
  `journal-emit` by hand, and every close goes through the user, also one an agent asks for in its `/checkpoint-3t`.
- Every `AskUserQuestion` of the supervisor is recorded in `decisiones.json` from its hook (the answer is kept as given
  and never counts as a yes). What the user types straight into an agent's pane appears in `supervisor.md` as a direct
  decision.
- Task governance (goalspec 0.47.0): every task gets the `goalspec:goal-adversary` round with another model; something
  terminal adds the external backend (`backends=both`).
- Digest and state: hidden agents are counted; events cut for room come back in the next digest; a registry entry whose
  pane holds another session is retired; hours from another day carry their date; the publication queue is reconciled
  at `inicia` and in every digest; the queue prints one short line per item and `libera` names the exact close command;
  an agent the check saw alive is not shown as silent; a background `monitor` (an artifact) is not work; the last line
  skips code fences; goal markers come from the whole turn; a `PreToolUse` block by another plugin's hook (read from the
  transcript at the end of the turn; in the measured setup no hook event reported it) is reported as such, not as the user's denial; a failure's signature keeps
  digits inside names; a session that is both supervisor and executor gets its state events.

## 0.8.1

- The supervisor explains every decision it asks the user for. Each one is a block that stands on its own: the
  problem in plain words, where it comes from (which agent, by tab), each option with what happens if chosen, a
  recommendation, and ids only at the end. A decision still open is asked again with its full block, never as a
  one-line reminder; one topic per question; the text of `lookout decision --abre` stands on its own too, since a relief
  supervisor reads it. The batch approval of `/lookout:pendientes` says what each pendiente solves in plain words.
  Seen on claude-vzert, 2026-10-06: three decisions asked as reminders ("plan A/B", "954 rutas", an id) could not be
  answered; with the context the user answered all three in one line.
- Fix: the supervisor's end-of-turn check ("no live waiter: launch `lookout espera`") never blocked. It ran from an
  async Stop hook, and an async hook cannot block: on claude-vzert it arrived six times as a loose note and the project
  went unwatched. It now has its own synchronous Stop entry (supervisor sessions only, behind `guard-sup.sh`).
- `lookout espera` prints the digest when it wakes and marks it handled, so the supervisor does not have to run
  `lookout resumen` between two waiters. Before, a waiter relaunched without `resumen` woke at once on the same old
  event; the supervisor took it for broken and stopped launching it.
- The supervisor never asks the user to run `lookout` or `herdr` commands.
- What the user must decide, run or paste goes in a code fence, which the terminal shows in color: the closing
  question of a decision, a command for the user, the «Como retomar» block. Nothing else, so it stands out.

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
