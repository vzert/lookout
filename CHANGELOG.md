# Changelog

## 0.13.13

- A relief whose work is not only measuring starts through goalspec (asked by the user, 2026-10-17: by hand they read
  the agent's «Como retomar» and, when it held anything but measuring, answered «sí, continúa, pero hazlo usando
  goalspec»; the relieved session had only «Usa /goalspec.» in its system prompt and did not use it). The supervisor
  judges the block before each `lookout relevo` (SKILL.md, «Relevo con goalspec»): only measuring (read, count,
  compare, run checks, report, change nothing) → no flag; anything else, or in doubt → `--goalspec`, and the new
  session gets `/goalspec:goalspec <trigger>` typed. Without the flag the trigger is byte for byte the old one. With
  goalspec not installed for the project the flag changes nothing and says so. A failed relief that is retried keeps
  the call of its first attempt. The line the supervisor reads for a live block, and the close brake, name the flag.
  A typed `/goalspec:…` reaches UserPromptSubmit as typed (measured on 2026-10-17 in lookout's events of
  `/goalspec:interview …` typed by the user), so its first delivery is confirmed by that event like the plain trigger.
  The transcript fallback of a retry does not recognise the slash form yet (Claude Code stores it as a command block).

## 0.13.12

- The supervisor can approve an agent's Bash permission dialog after the user's yes in its modal (asked by the user,
  2026-10-17: the user said yes in the modal and still had to go to the pane). The agent's PermissionRequest hook now
  writes the whole command in its `blocked` event (it kept 200 characters). `lookout decision … --permiso` ties a
  decision to the agent's pending request and prints the whole command for the modal's question; the modal's hook
  closes it with the user's own choice. `lookout aprueba PROYECTO AGENTE --decision dN` presses «Yes» once (never
  «Yes, and don't ask again», never «switch to auto mode»), and only when the yes is the user's for this agent and
  unused, the agent's last event is still that request, herdr sees it blocked, and the dialog at the bottom of its
  visible screen, read by its whole shape, shows exactly that command, wrapped wide (a break at a space eats it) or
  narrow (a break mid-word). A dialog taller than the pane pushes its header off the visible screen: then nothing is
  pressed. The dialog must have its top border right above the header, as wide as its rules, and its options numbered 1..N with one «Yes» and «No» last, and the user's yes
  counts only for a modal question that showed the whole command, exactly and between «» (as the modal's hook wrote
  it down). A wrap eats one space, and only where the next word did not fit; a command with a newline is never
  pressed. The dialog's command lines carry the bar «│» (one call) or not (two calls in one message): both are read.
  The yes is spent before the key, and the request and the screen are checked once more right before it. A window
  of one herdr call stays between that check and the key; the user accepted it, and from the key until 3 s after the
  dialog closes (or until it gives up) lookout watches for another request of the agent and warns loudly if one
  comes. Anything else presses nothing, not even
  Esc, and says why.

## 0.13.11

- The alta and the sweep go on while the supervisor's modal is open. Only the waiter's checker thread ran them, and
  AskUserQuestion holds the supervisor's turn until the user answers: in 3-tier-memory (2026-10-16) the waiter launched
  before a modal woke at once on 11 events that had arrived during the turn and exited, and the project went 65 min
  with no alta and no sweep. Now the supervisor's own PreToolUse[AskUserQuestion] hook starts a vigía (`bin/vigia.py`),
  a process detached from the hook with its own pidfile (never the waiter's, which the Stop check reads as «waiter
  alive»). While no waiter of the supervisor is alive it runs the waiter's checker pass every `LOOKOUT_REVISA_CADA`
  seconds; a lock (`revisor.lock`) keeps one pass at a time between the vigía and a waiter. It leaves when the modal
  ends (its answer, a failed modal, a prompt, a Stop or a SessionStart of the supervisor), when its supervisor no
  longer supervises, or after `LOOKOUT_VIGIA_HORAS` (12). A late answer of an older modal leaves the open one watched.
  What a pass finds goes to events.jsonl as before, and the supervisor reads it when the modal ends.

## 0.13.10

- An agent with a live background shell can take input again. A shell keeps herdr «working» after the turn ended
  (the footer «· N shells ·», matched by a local herdr detection rule), and `envia`, `entrega`, `recarga`, `relevo`,
  `cierra-pestana` and the sweep of the alta refused it until the shell ended, forever for a shell that never ends.
  Measured 2026-10-17 in the transcripts: 19 «está working» refusals, 2 of them test benches; of the 17 real ones, 10
  were an agent quiet since its Stop (8 on 2026-10-15, two agents, four tries each). Now herdr's «working» counts as
  quiet when the agent's last event is a Stop (`idle` or `bg_wait`) and its transcript has nothing after it but the
  Stop's own system rows; replayed on those 17, it lets through exactly the 10. The other 7 stay refused: 4 had a hook
  event of a turn (`working`, `fallo`), 1 had no Stop yet, and 2 were turns opened by a task notification or a
  message, which fire no UserPromptSubmit but do write the transcript at once. `blocked` and `unknown` are never quiet, and the
  input box is still read after this check. Only `system` rows and Claude Code's undated bookkeeping rows
  (`last-prompt`, `cost-state`, `mode`…) may follow the Stop; a row with no or a bad timestamp of any other type, a
  line it cannot read, or a tail of the transcript that does not reach the Stop count as a turn (adversary round 1:
  a 400 kB row after the Stop left only a fragment in the tail it read).
- `/exit` with live background work opens Claude Code's «Background work is running» dialog (Exit and stop tasks /
  Move to background and exit / Stay). `cierra-pestana` and `relevo` waited for a SessionEnd that never came and left
  it open in the pane. Now they check for live work before typing `/exit` (the last Stop's tasks, or the footer's
  count, which also covers a monitor) and stop with a NO that asks the supervisor for a modal. Stopping a shell kills
  a process, so the choice is the user's: `lookout decision … --abre … --agentes <agente> --shells-parar "<label>"
  --shells-dejar "<label>"` records which of the two labels the user picked in the modal (exact label, written by
  the hook; any other answer, such as wait, authorizes nothing). With `--shells dN` the command presses that option's
  own number in the dialog (the number alone picks it, measured live), read by its whole shape: a ▔ border,
  «Background work is running», the three options and «Enter to confirm · Esc to cancel» ending the screen, read
  as one text so a narrow pane that wraps it still counts (the same options typed in the prompt box do not).
  A footer cut to «· 2» by a narrow pane counts as live work. The decision must name
  the agent and be newer than its last Stop. A dialog that opens with no choice on record (a shell started in
  between) is cancelled with Esc, which only undoes lookout's own `/exit`, and the supervisor gets the same request.
  With the user's choice, the background guard of `cierra-pestana` gives way to it.

## 0.13.9

- The user's yes is written by the modal's hook, not by the supervisor. `lookout decision … --abre … --si-es "<label>"`:
  when the user answers that decision in the supervisor's modal, the hook closes it, yes only if the user picked that
  exact label (`por_hook`). No `--cierra … --si` is needed. 3-tier-memory 2026-10-16: auto mode denied the
  supervisor's `lookout decision --cierra d113 … --si` as «Auto-Mode Bypass», so `lookout envia --usuario-confirmo
  d113` refused and the user had to open the PR himself. `--cierra` on a decision the hook already closed says so and
  changes nothing. Every flow where a yes authorizes something (typing in an agent's pane, a push, one more adversary
  round, closing, discarding or freeing a pendiente) now tells the supervisor to open the decision with `--si-es`:
  both SKILLs, every refusal that asks for `--usuario-confirmo`, the next step of `publica`, the digest line of
  an agent waiting for typed text, the escalation after two failed corrections, and the message of a `decision --abre` without it. The user's choice must be the label exactly, spaces included, and the label is kept as given (adversary
  rounds 7 and 10: « Cerrar » counted as «Cerrar», and a label « Cerrar » never matched).
- A «Como retomar» that opens with «Ninguno», «Ninguna», «Nada», «None» or «Nothing», whatever punctuation or
  formatting follows, and cites a pendiente still open is `ambiguo` («dice «Ninguno» pero cita pendientes»): the
  supervisor asks the user whether to close or relieve it. It is never `vigente` (relieved without asking) nor
  `nada`. Same day, «Corrección snipet de cierre»: «Ninguno — … (p-f8df9ea916) espera a que se acumulen cierres, con
  recordatorio el 2026-10-22» was relieved as `vigente`. lookout does not read the words after «Ninguno» (two
  earlier tries at that let through wordings with work left, adversary rounds 3-4). The words after «Como retomar»
  count after any colon, dash or formatting (underscores too), and a «Ninguno» counts as finished only when nothing
  after it in the turn cites a pendiente (adversary round 5: «Ninguno.» with the pendiente on the next line closed
  the tab on its own, as it did since 0.13.0). A «Ninguno» whose cited pendientes are all closed is still finished.
- `lookout cierra-pestana … --usuario-confirmo dN` closes a tab the user decided to close. dN must be a close decision
  (`--abre … --agentes <agente> --cierre --si-es "<label>"`), approved by the hook from the user's own choice, and
  opened after the agent's last turn. It skips only the checks that read the agent's own words (finished? a question
  in its last turn?); the screen, git, a pending publication, an open decision, an unanswered message and a
  background task still stop it. A yes to something else, an older one, or a `--cierra --si` of the supervisor closes
  nothing. The close of a failed relief takes the same kind of decision, opened strictly after the failure.

## 0.13.8

Three agents of 3-tier-memory sat unseen for hours on 2026-10-16 while the digest called them «terminó su turno» or
«espera tarea de fondo».

- A wait for something typed in the agent's pane now holds until something releases it. pendientes-en-sessionstart
  asked for «aprobado» in two turns, then ended five more with «Sigo esperando tu «aprobado» en esta ventana» or
  «… aquí», which 0.13.7 did not read as a wait; the wait vanished and the agent sat 7 hours. At each end of turn
  the agent's hook reads its transcript tail: a wait starts with an assistant text read as one, or with goalspec's
  ratify brake denying a tool; it ends with a Bash, Edit, Write, MultiEdit or NotebookEdit that ran, a `!` typed in
  the pane (`<bash-input>`), or a prompt typed there that is not a peer or system message (`isMeta`, a harness tag)
  nor lookout's own report note. The phrases also read a quoted «aprobado» someone waits for and «aquí» / «esta
  ventana» after a verb of typing (no false wait over the 81 turn endings of the two sessions measured). The
  agent goes to «Te necesita», and the digest prints `↳ ESPERA ALGO TECLEADO EN SU PANE …` under its row on every
  wake. The phrase reading is still approximate; the brake and the hold are not.
- Hooks older than the installed plugins are named. An agent opened before `claude plugin update` keeps its old hooks
  until /reload-plugins in its own session: prompts-repetidos ran 3-tier-memory 2.62.0 with 2.62.6 installed (its
  close guard looped over a bug fixed in 2.62.3), 3tier-snippet-linea-extras lookout 0.12.1 (no `retomar`, so its
  «Como retomar: Ninguno» never closed its tab), pendientes-en-sessionstart lookout 0.13.5 (no `espera_pane`).
  - Every event the agent's lookout hooks write (`on_state.py`, `on_ask.py`, `permisos.py`) carries `v`, the hooks'
    version. With 0.13.8 or later installed, an agent whose last event from a Claude hook (`hook` = Stop,
    UserPromptSubmit, PermissionRequest…; not the supervisor's own `descubre` / `registro` / `barrido`) has no `v` or
    an older one runs old lookout hooks.
  - For any other plugin, the version in `…/plugins/cache/<marketplace>/<plugin>/<version>/` printed inside a hook
    attachment of the agent's transcript (3-tier-memory's recall prints its own path), against
    `installed_plugins.json`. A path the agent read or ran itself does not count.
  - The digest prints `↳ hooks viejos: <plugin> <version> (instalada <version>) → lookout recarga <proyecto> <agente>`
    under the agent's row. New `lookout recarga`: types /reload-plugins only into an idle agent with an empty box
    (a suggestion counts as empty, a draft never), confirms it by a new «Reloaded:» on its screen, and records the
    installed versions in the registry (`recargado`), which clears the line until the next update. Unconfirmed, it
    says so and records nothing.
- A background task that keeps an agent waiting warns again: at 1×, 2×, 4×… `LOOKOUT_LARGO_S` (1 h), not once.
  3tier-snippet-linea-extras had a shell alive 24 h after its single warning. The event carries the task and
  `reservada` (what D6 reserves to the user in its command, `permisos.reserved`); the digest says to ask the agent
  by SendMessage whether it still needs it and to stop it with TaskStop, or, when it is reserved, to ask the user.
  lookout never kills a process.
- The supervisor skill says what to do with each of the three lines.

## 0.13.7

- The supervisor is the user's only channel to its agents: what an agent needs typed in its own pane is asked in the
  supervisor's modal and typed there by the supervisor. goalspec's ratify brake is released only by a prompt typed in
  the agent's session, never by the supervisor's SendMessage; the supervisor told the user to go and type «aprobado»
  in the agent's pane, and the agent sat idle until the user found it (3-tier-memory, 2026-10-16). The same held for a
  `! comando` an agent handed the user to run there.
  - `lookout envia <proyecto> <agente> --usuario-confirmo dN --texto "<texto>"` types the user's decision into the
    agent's pane. It refuses (exit 5, nothing typed) unless decision dN was answered yes by the user, names this agent
    (`--agentes`), and the text (one line, ends trimmed, spaces inside as they are) is either the user's whole
    literal answer or a whole quoted span («…», `…`, "…") of the modal's question, as the supervisor's own hooks wrote
    them down (never the supervisor's `--abre` or `--respuesta` text; a decision with no answer of the user on record
    types nothing). A prefix of the approved command or the same characters with a moved space do not pass: a
    supervisor cannot type what the user did not see. A text gets ` (dN)` appended; a command (`!`) or a slash command goes as is. Each
    decision types once (key `usuario:dN`). A text with a `!` command on any line always needs `--usuario-confirmo`. `deliver.py` run by hand refuses
    such a text (exit 4): a command reaches an agent only through `lookout envia --usuario-confirmo`. A supervisor that
    calls `herdr agent prompt` itself is outside what lookout can stop; the skill forbids it.
  - A `! comando` delivered this way runs in the agent's shell mode and fires no UserPromptSubmit (measured
    2026-10-16 with a throwaway Claude through `herdr agent prompt`); delivery confirms it from the agent's transcript
    (`<bash-input>`), counting only runs after the send, so the same command run earlier never confirms it.
  - The agent's end of turn marks `espera_pane` when its last message waits for something typed in its pane («… en
    este pane», «escriba aprobado», a `! comando` for the user) or goalspec's ratify brake held a tool this turn, also while a
    task of its own runs. That end of turn wakes the supervisor even after a report, and the digest says what to do. A false wake is the safe
    side, as for a question. The phrase detection is approximate: a wait worded otherwise is missed, and then only an
    end of turn without a report wakes the supervisor (as before 0.13.7).
  - The supervisor skill drops «give the user the exact command to run in the agent's pane»; the deny of
    AskUserQuestion tells the agent to ask for the typed text by SendMessage and never send the user to its pane.

## 0.13.6

- An agent's marker keeps every address its supervisor had. After a relief of the supervisor the markers
  (`sessions/<session_id>.json` under lookout's state) held only the new address (3-tier-memory, 2026-10-16: 2476.sock
  → 95700.sock), so 3-tier's `checkpoint-close-guard` (2.62.3) stopped counting the questions the agent had already
  sent to the old supervisor. New key `direcciones`: a list of strings, every non-empty address the session's
  supervisor had in this project, without repeats, the current one last. `address` does not change: it is still the
  current address as a string (`""` with no socket, and `""` for any value that is not text, which 3-tier reads as
  unreadable). A marker written before 0.13.6 counts its `address` as the first
  entry. An agent's relief carries the list to the new session. Reading `direcciones` is 3-tier's side; until 3-tier reads it, its
  `checkpoint-close-guard` behaves as before (only `address`), so questions sent to an earlier supervisor still do
  not count there.
- `lookout publica <proyecto> <agente> --worktree <ruta>` checks the agent's own worktree. An agent launched on the
  main checkout that works in a worktree of its own (`cd` in its Bash) is registered with the main checkout, the only
  tree herdr sees; `publica` checked that checkout's branch and answered BASE-MOVIDA for branches that did contain
  origin's tip (3-tier-memory, 2026-10-16: aviso-sin-git and plan-poda-guardian). The path must be a checkout of the
  same repository (`WORKTREE-AJENO` otherwise, exit 5, nothing queued); it stays with the publication, so `--hecho`
  and the queue's expiry read the same tree without the flag. A BASE-MOVIDA or NADA checked on the main checkout of a
  repository that has other worktrees now says to ask the agent for its path and repeat with `--worktree`. The
  supervisor skill says when to pass it.

## 0.13.5

- An agent whose alta could not rename it names itself in herdr. The alta renames once, from the waiter; a box with
  the user's draft at that moment («caja con borrador») left the agent without its herdr name until the supervisor
  delivered the note (3-tier-memory, 2026-10-16: a session registered in 16 s while the user typed its first
  prompt). Now the agent's own state hook finishes it on its next hook event: it runs inside that session, and its
  `HERDR_PANE_ID` is that session's pane; herdr must still answer and see this same session there (a pane moved to
  another workspace gets a new id). It runs on its asynchronous events only (end of turn, prompt, notification), never
  on the synchronous SessionEnd. Only herdr's side (agent, pane, tab), nothing typed into the box (the session's own
  `/rename` still comes with the note); only when the alta recorded «caja con …», herdr shows no other name for it
  (one the user gave is kept), and at most 3 times, a half-done try included; an agent retired or relieved meanwhile
  keeps its record. `lookout entrega` renaming it ends those tries. Residual: between that check and the rename call
  (milliseconds) the session would have to exit and another start in the same pane; then only a herdr label changes,
  which can be renamed back (the alta and `lookout entrega` have had the same window since 0.13.1). A retry from the waiter was tried first
  and dropped: from outside, the pane's session could change between the check and the rename (adversary, three
  rounds).

## 0.13.4

- A relief no longer asks herdr for a name it refuses. `lookout relevo` of the 32-character
  «agente-3-tier-memory-prueba-de-l» asked for «…-2» (34 characters); herdr answered `invalid_agent_name` after the
  `/exit`, and the tab was left with a bare shell (3-tier-memory, 2026-10-16). `unique_name` now cuts the base so the
  suffix fits in herdr's 32 characters, like the alta's names since 0.13.3.
- A failed relief stays in «Te necesita» on every wake (`relevo fallido → díselo al usuario; lookout relevo otra vez o
  lookout cierra-pestana`) instead of going to «terminados», and its output asks the supervisor to tell the user: the
  supervisor saw it once, in the command's exit code 4, and never said it. The session that never started is no
  longer a «sin eventos» row.
- A failed relief can be closed. `cierra-pestana` refused it (its pane is a bare shell and its last turn keeps the
  block), so the row had no way out. Now `lookout cierra-pestana … --usuario-confirmo <dN>` closes it when dN is a yes
  of the user opened after the failure and naming the agent, its pane holds no other session (read from the pane, not
  from `agent list`) and the git guards pass; there is no `/exit` (its session already ended). A tab the user already
  closed leaves the table without a decision, and what the git guards find there goes to the user.
- The skill check asks for a reload only when the installed lookout is newer than the loaded skill text (semver
  order, pre-releases included), and reads the transcript again from the start when it was replaced in place.
- The supervisor learns when the skill text it loaded is older than the installed lookout. `/plugin` and
  `/reload-plugins` update the hooks and the `lookout` command, but not a skill text already read: in 3-tier-memory the
  supervisor went on with 0.10.0 for a whole day, and on 2026-10-16 with 0.13.2 while 0.13.3 was installed. Its Stop
  hook now reads the last «Base directory for this skill» of `lookout:supervisa` in its transcript, compares it with
  `installed_plugins.json` and, when they differ, tells it once (per pair of versions) to load the skill again with
  the Skill tool; the user sees one line.
- The decisions about pendientes come before an agent's `/checkpoint-3t`, not halfway. A supervised agent cannot open
  the checkpoint's modal, so «haz tu checkpoint y mándame la lista» split it in two turns: the agent wrote its session
  file, stopped halfway, 3-tier's close guard blocked it twice and the pendientes were emitted after the audit
  (3-tier-memory, 2026-10-16). The supervise skill now asks the agent for its candidates first, puts them to the user
  in one modal, and only then sends «Haz /checkpoint-3t de un tirón con estas decisiones: … (dN)»; the note to the
  agents says to send its plan before starting `/checkpoint-3t`, not halfway through it.

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
