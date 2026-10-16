# Changelog

## 0.13.3

Found by measuring 0.13.2 in the live supervision of 3-tier-memory (2026-10-16).

- The alta gives a name herdr accepts. herdr labels a new tab with its place in the list («12» on tab number 24), and
  lookout took that label for one the user chose: the agent was named «12», which herdr refuses as an agent name
  (`[a-z][a-z0-9_-]{0,31}`), so the rename was left halfway and the session itself was renamed «12». A label of digits
  only is now herdr's; a name that does not start with a letter gets `agente-` in front, and names stop at 32
  characters (a folder like `3tm-utf8` failed the same way).
- A «Como retomar» nobody attended stays in «Te necesita». The `retomar` event is announced once; the agent then sat
  under «Trabajando» with «estaba quieto con un «Como retomar»» for two hours, and the supervisor never opened the
  modal for its ambiguous block. The row now reads `bloque vigente|ambiguo HH:MM:SS → lookout relevo | modal «¿relevo,
  cierro o lo dejo?» | lookout cierra-pestana (terminó)`, is repeated on every wake (the waiter's «sin cambios» no
  longer folds it), and leaves when a decision opened with `--agentes <agente>` names it, the agent is relieved or
  closed, or it works again. No herdr notification to the user for it.
- The `retomar` line says what to do before the motive, which the line's width could cut; `cierra-pestana`'s brake «es
  un relevo, no un cierre» says `lookout relevo` or the modal.
- Supervise skill: launch the waiter before the modal when it has left (a modal open for an hour left the project
  without altas or sweep), and the new «Te necesita» row.

## 0.13.2

Found by measuring 0.13.0 in the live supervision of 3-tier-memory (2026-10-15): `cierra-pestana` could close none of
the 8 older agents, because 6 unpushed commits of one session in the shared checkout blocked all of them; and an agent
quiet since before 0.13.0 with a live «Como retomar» was never read, because the block is read only at its Stop or
when it is registered.

- **Behavior change:** a «Como retomar» is relieved by default. It is `vigente` when at least one cited pendiente is
  still open (the closed ones are dropped) and no other registered agent, or a subagent of one, worked on it after the
  block: a command, edit, message or task of its that names it (a Read, a Grep or a question does not); retired and
  relieved sessions count. Closed means «- [x]» or listed in `memory/pendientes/_resueltos.md` or `_caducados.md`; a
  p-id found nowhere (a `pendiente.add` not compacted yet) is not closed. All closed, or a
  block of unknown time, is `ambiguo`; `cierra-pestana` takes the all-closed one as finished. A mention in a pasted prompt, a hook's context or a
  file it read is no longer work, and the block's age no longer matters (`LOOKOUT_RETOMAR_HORAS` is gone). On
  3-tier-memory a pasted resume prompt that named a p-id made a live block ambiguous, and the supervisor asked the
  user about 5 blocks, recommending not to relieve. The supervise skill now recommends «Relevarlo» in that modal unless
  another agent worked on it.
- `cierra-pestana`: an unpushed commit belongs to the registered session (or one of its subagents) that had a Bash call
  whose command says «commit» running at the commit's time. That covers `-q`, subagents and scripts called from such a
  command, which print no «[rama hash]». A relieved owner's commits pass to its live successor. A commit owned only
  by other live agents no longer blocks this one; a commit with no known owner, or one of a retired session, still
  blocks. The hash an agent printed is no longer
  used. On 3-tier-memory the 6 commits fall to one session and to no other.
- The waiter's discovery pass (every `LOOKOUT_DESCUBRE_CADA` s, 120) also reads the last turn of each registered agent
  herdr sees idle or done, and writes one `retomar` event per block and classification (hook `barrido`): a block its own
  Stop already announced is not announced again, and one whose classification changed (an ambiguo now vigente) is. A transcript that did not change
  since the last pass is not read again.

## 0.13.1

Found in the live test of 0.13.0 in 3-tier-memory (2026-10-15): two sessions launched by hand were registered but kept
their old names. The supervisor read the waiter's digest through its own `grep` (23 times in that session), missed
both `agente nuevo` lines, and never ran `lookout entrega`.

- The alta renames a new agent itself: `/rename` of the session, herdr's agent and pane names, and a tab with herdr's
  default label, as `lookout entrega` does. With text in its input box it types nothing and the `nuevo` line says
  `sin renombrar (caja con …)`; if herdr refuses the `/rename` it says `sin renombrar`, and if it refuses the agent, pane or tab name, `renombrado a medias`. The note still comes from
  `lookout entrega`, which no longer types a second `/rename` in a session whose title already is the agent's name, and no longer
  records or reports as done a name herdr refused (its output says `A MEDIAS`). The supervise skill says what to do
  with `renombrado a medias`.
- The supervise skill tells the supervisor to read the waiter's output whole, never through `grep`, `tail` or `head`:
  the digest marks its events handled, so one a filter hides does not come back.
- The waiter's checker thread ends when its wait ends. An in-process wait in the tests left it running, and it wrote
  `projects/pF4/descubre.json` in the user's real state.

## 0.13.0

The supervisor takes care of the agents' life cycle: it relieves an agent that left a live «Como retomar», closes the
tab of a finished one and takes in an agent launched by hand; and its context budget follows the model's window.
Found in a real supervision of 3-tier-memory (2026-10-15): 2 live blocks and 0 reliefs, 3 finished agents with their
tab open, and a supervisor that asked for a relief it did not need. Scope decided by the user.

- **Behavior change:** the supervisor's budget is 80 % of its model's window when that is above the fixed limit
  (arranque + 300k, or 370k). The window comes from the model line Claude Code writes in the transcript
  («claude-opus-5-5[1m]»): a 1M supervisor now asks for its relief at 800k, not at 370k (it read «382k de 370k …
  PRESUPUESTO SUPERADO» six times). A 200k window, or one lookout cannot read, keeps the fixed limit.
- An end of turn with a «Como retomar» carries `retomar` (`vigente`, `ambiguo` or `nada`, the cited pendientes and why):
  `vigente` when every cited p-id is still open in the project's `memory/_pendientes.md`, no other registered agent
  cited them after the block, and the block is from the agent's last turn and younger than `LOOKOUT_RETOMAR_HORAS`
  (24 h). It also recognizes 3-tier's «🔁 Siguiente sesión — copia y pega:» and «Como retomar: Ninguno — …». Such a turn
  wakes the supervisor even when the agent already reported. Registering an agent that is already idle with a block
  writes a `retomar` event.
- `lookout relevo` works for an agent the user launched (no task of lookout), reads the block only from the agent's
  last turn (a stale one under newer messages no longer counts), and starts the new session with the old one's model
  (with its window), `--effort` and `--permission-mode`, read from its transcript. If one cannot be read it does not
  relieve. It gives no port to an agent that had none. `/exit` that does not exit still aborts.
- New `lookout cierra-pestana <proyecto> <agente> [--motivo "<cita>"] [--revisa]`: closes the tab (or only the pane)
  of a finished agent after two signals (its last turn says it finished; herdr idle with an empty box) and guards that
  each stop it: uncommitted changes of its own, unpushed commits in its tree (strict in a shared checkout), a queued
  publication, an open decision naming it, a message of its to the supervisor with no answer, a question in its last
  turn, a background task. A goalspec completion marker alone is not «finished».
- The waiter's checker registers a Claude session of the project that is not in the registry every
  `LOOKOUT_DESCUBRE_CADA` s (120) and wakes the supervisor with `nuevo`, who delivers its note.

## 0.12.2

Fewer wakes of the supervisor, a shorter waiter digest and four output bugs, measured on a real supervision of
3-tier-memory (2026-10-15: 36 waiter wakes in 7.6 h, 61 % with nothing to do, ~1.9 KB each; scope ratified by the user).
Replayed over that session's events, the new wake rules give 16 wakes instead of 33 (an approximation: it does not
model the supervisor's own pace).

- **Behavior change:** «espera tarea de fondo» (`bg_wait`) no longer wakes the supervisor (19 of the 36 wakes), unless
  the turn that ended asked something (any «?», «¿» or «？» in its last message). It stays in the next digest. An agent whose background
  wait passes `LOOKOUT_LARGO_S` (60 min) wakes it once as `largo`; the no-progress check did not look at a background
  wait before.
- The waiter waits 3 s (`LOOKOUT_VENTANA`) after its first event, so a burst wakes the supervisor once (11 of 36 wakes
  came less than 5 s after the waiter started); its timeout no longer runs during that wait. `lookout espera` no longer prints the «evento:» line; the digest
  under it starts with that same event.
- The waiter's digest prints the agents table, the open decisions and the publication queue only when they changed
  since the previous wake (`sin cambios` in one line otherwise); `lookout resumen` still prints everything. The
  `Contexto:` line shows from 60 % of the budget. The echoes of the supervisor's own messages, task notifications and
  herdr's `idle_prompt` notices are no longer listed as events (they are counted).
- An end of turn shows the last line of its message that asks something («?», «¿», «？»), or the line that opens a list,
  instead of only its last line; a background wait shows the task's description before its command.
- The first `lookout resumen` after several waiter wakes shows again only the last wake, not every event since the
  first one (it repeated 158 events in 3-tier-memory).
- The Stop hook of the supervisor no longer asks it to relaunch the waiter while that waiter's wake notification is
  still queued (5 of 5 reminders came then; 2 of them led to a second waiter that died with «waiter ya vivo»).
- `lookout entrega` confirms the `/rename` by the input box going empty, not by a UserPromptSubmit that the built-in
  `/rename` never fires: it saved 30 s per agent (6 of 6 deliveries).
- `lookout publica`: a refused check no longer leaves the agent «turno» in the queue (it stayed 6.6 h and held the
  queue); asking again re-checks from the start. In a checkout shared with other registered agents, only the
  uncommitted files that another live agent of that tree wrote with an Edit/Write that succeeded, and this one did not
  (from their transcripts), are listed as
  a warning instead of making it `SUCIO`, since a push carries commits only. Any other uncommitted file still counts,
  also one written in a way lookout cannot see (a script, `git stash pop`, a subagent), and so does every file in the
  agent's own tree. The waiter's own digest says the waiter that woke it left, not a flat «Waiter: no hay».

## 0.12.1

- The `tail -F` that the waiter (`lookout espera`) and a delivery use to follow `events.jsonl` now dies with the
  process that started it, also when that process is killed with SIGKILL and no cleanup runs. Before, `tail -F` stayed
  alive forever waiting for the file: one machine had 1,483 of them, up to 12 days old, most left by test runs that
  kill their waiters (reported from Will-Ops, 2026-10-15). The tail now runs under a small `sh` guard in its own
  process group. The guard waits on a pipe that only the starting process holds open; when that process ends, for any
  reason, the pipe closes and the guard ends the tail at once. It needs no `ps`, does no polling and trusts no process
  id. A normal end kills the group. Lines still reach the waiter as soon as they are written.
- `wait_event.wait()` no longer leaves its timeout alarm armed after it returns.

## 0.12.0

The supervisor asks the user in a modal, never in prose (measured on 3-tier-memory, 2026-10-15: with four agents
reporting, two decisions went out in prose 34 s apart, five of the next eight turns only said they were still open,
and the user never answered them; they asked for `AskUserQuestion`).

- **Behavior change:** `/lookout:supervisa` and `/lookout:pendientes` put every decision of the user in one
  `AskUserQuestion`, also while agents are alive (0.10.0 asked in the chat then). First the supervisor answers
  whatever reversible questions it has queued, then it opens one modal with all pending decisions (up to 4). The
  context goes inside the modal: the question states the problem and where it came from; each option says what
  happens and whether it can be undone. No prose block before the modal and no "still open" reminders. While the modal
  is open, agent messages wait in the queue.
- A new reminder at the supervisor's turn end: a decision opened with `lookout decision --abre` that the user has not
  answered (in a modal or in the chat) is reminded once, with the way to close it if it no longer applies. It goes out with the "no live waiter"
  reminder in the same output, waiter first (the modal holds the turn until the user answers).
- Both turn-end reminders now go out as non-error Stop feedback (`hookSpecificOutput.additionalContext`) for the
  model plus a one-line `systemMessage` for the user, instead of a `decision: block` with the full instructions. The
  user sees a short line, not the model's orders, and no hook error notice.
- One modal now carries several decisions, whatever their age (a question used to attach to the last decision
  opened in the previous 2 minutes). Each question names its decision at the end (`(d3)`) and attaches only to that
  one; a decision counts as answered only when the answer to its own question arrives. A question without an id, or a
  modal dismissed without an answer, leaves the decision waiting, and the turn-end reminder names it. An answer is still never a yes: only
  `decision --cierra … --si` authorizes.
- The texts printed by `lookout publica`, `gobierno` (round cap), `cierra` and the correction cap point to the modal.

## 0.11.0

Agents in tabs on the main checkout, not in worktrees (docs/plan.md, Fase 9 G; measured on claude-vzert and decided by
the user, 2026-10-08).

- **Behavior change:** every agent of `/lookout:pendientes` runs in its own herdr tab on the main checkout. A worktree
  (`<repo>-wt-<slug>`, branch `lookout/<slug>`) only when the user asks for it: `lookout pendientes <project>
  --worktree <id>`; `--en-main <id>` takes it back. On claude-vzert the first batch's agents left 3 `-wt-` folders
  and 3 `lookout/*` branches holding only a report, in a repo with no code of its own.
- A code task on the main checkout edits without commit and lists every file it changed in its report; the user
  commits. It does not change branch or use stash, reset, checkout, switch, restore, clean, rebase, merge or commit:
  the tree is shared with the user and other agents. A PreToolUse hook denies to agents lookout launched on the main
  checkout the git forms that move the shared tree, index or branches (also add, rm, mv, update-ref, update-index,
  sparse-checkout, symbolic-ref, apply --index, bisect, worktree, and branch unless it lists), also inside `( )`, `$( )` or backticks. It lets through `git add` and `git commit --only` whose
  paths are all under `memory/` (the /checkpoint-3t form). It reads the command text: a rail for slips, not a full
  barrier (it does not see `sh -c`, `eval`, git aliases, git called through a variable like `$GIT`, or git run from a
  script). A git with `$`, a backtick or `{a,b}` before its subcommand is denied: the subcommand cannot be read.
- A measurement, a message or a credential task stays read-only (no edit tools), also after a relief; read-only no
  longer means "no worktree".
- Two code agents on the main checkout get two dev-server ports: there the port belongs to the agent, not to the
  folder. (Two of your own sessions on the same linked worktree still share its port, as before.)
- A code agent that failed on the main checkout is not proposed again until the user decided about its half-done edits
  (`lookout pendientes <project> --reintenta <id>`; `libera --fallida` says so).
- The stall check no longer takes a change in the shared tree as progress of an agent on the main checkout.
- `lookout publica` refuses an agent lookout launched on the main checkout (`EN-MAIN`): the commit and the push are the
  user's. Your own sessions that lookout discovered on main go through `publica` as in 0.10.0.
- `lookout puerto` gives each session discovered on the main checkout its own port (two of them no longer share one).

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
