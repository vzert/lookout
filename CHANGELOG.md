# Changelog

## 0.13.40

- A Stop now carries its «Como retomar» even when the hook reads the transcript before Claude Code has written the
  turn's last row. `retomar.para_agente` takes the hook's `last_assistant_message`: when the transcript does not end
  with it, that message is the end of the turn, dated now. On a bench (2026-10-19) the first Stop of a newly registered
  agent came without `retomar` 127 ms after its text row was created; the waiter's sweep found the block 61 s later.
  The most likely cause is that the row was not on disk yet; a swallowed error is not ruled out (see below). With
  only the previous turn on disk, the Stop carried that turn's block as `vigente`.
- An error while reading the block is no longer silent: the Stop event says it in `retomar_error`.

## 0.13.39

- The supervisor reacts to a message of its own that another session held, not only at registration (p-c1cb6123e4).
  0.13.33 matches an agent's permission mode when it registers it; an agent moved to bypass later holds every message
  of the supervisor until the user approves it. Claude Code tells the sender with a `[Cross-session delivery notice]`
  in its own session («held by that session», then «denied by the recipient user» when the dialog is closed; both
  measured 2026-10-19). The supervisor's UserPromptSubmit hook now reads it, finds the agent by the recipient's socket
  (`<config>/sessions/<pid>.json`, `messagingSocketPath`), and puts one `retenido` line in the digest, what to do
  first: with no dialog on the agent's screen, a bypassing agent is lowered with Shift+Tab as at registration; with the
  hold dialog on screen, or a pane where herdr does not show that session now, nothing is pressed and the supervisor
  asks the user to approve it; a retired or relieved agent is never pressed. After a denial or expiry the line says to
  resend it: SendMessage now logs its `msg_id` and whole text, and `lookout reenvia <proyecto> <msg_id>` prints that
  text as it was sent. The line is never folded, never clipped and never taken for the agent's own state (digest nor
  supervisor.md). Expiry and release notices were not seen: they are read by the same shape; one that says «expir»
  counts as dropped, only «released» or «delivered» counts as delivered, and any other wording says that lookout does
  not know whether it arrived.
- That notice is no longer taken for the user's answer in the chat (supervisor) nor for a decision the user took in an
  agent's pane (agent).

## 0.13.38

- A publication checked again no longer keeps the reason of its earlier refusal or expiry. `lookout publica` reuses
  the agent's caducada or rechazada entry and never dropped its `motivo`, so `--hecho` carried it on: in 3-tier-memory
  (2026-10-18) PR #40 sat in publicaciones.json as `pr-abierto` with «su HEAD cambió después de verificarla», although
  its head was the PR's. Only the JSON showed it, not supervisor.md nor `--cola`.
- Every herdr notification lookout sends (an open decision, a state change, an unattended «Como retomar», a permission
  request or an auto mode denial, the supervisor's relief) goes through `herdr_cli.notifica`, which writes one line
  to the project's `avisos.jsonl`: time, kind, title and herdr's exit code (plus its error when it failed). A title
  with a broken character is written escaped. When the project's state folder cannot be written the notification
  still goes out without its line: a failing log never stops a notification. Before,
  `avisa_bloques` called herdr without looking at the result, so a live test could not tell the notification went out
  unless the user looked at the screen (banco 2026-10-19). A test fails if a module calls `notification show` directly.
- The pkill brake keeps two known limits, now written next to its code, by the user's choice (p-4f3fe84d89): a
  pattern that only reaches sessions lookout did not start (the supervisor, an agent started by hand) passes, and a
  kill inside a quoted string another program runs (`xargs -I{} sh -c "pkill -f {}"`, `watch "pkill -f claude"`) is
  not read. Covering the first would mean judging every claude on the machine, the ones the user kills on purpose
  included.

## 0.13.37

- supervisor.md no longer lists the session a failed relief never started. The summary hides it since 0.13.4, but
  `supervisor_md.render` only skipped relieved and retired agents, so «agente-3-tier-memory-prueba-de-l~3b9909 |
  fallida | sin eventos» stayed in 3-tier-memory's supervisor.md from 2026-10-16 to 2026-10-19. The agent whose relief
  failed still shows, and so does a failed launch that was no relief.
- The supervise skill tells the supervisor not to state what an agent's input box holds from an earlier reading:
  `lookout relevo` reads it at that moment and answers `NO: la caja de … tiene …` when it has text, and that line is
  what goes to the user. In 3-tier-memory (2026-10-16, d42) the supervisor said the box held a user draft, from a
  reading 18 h old, and asked instead of relieving.

## 0.13.36

A queued agent is told by the supervisor to wait its turn, instead of being left to work unsupervised (user's decision
2026-10-19, after 0.13.34 was published: that gap was not acceptable). It is a message: lookout does not register or
pause the agent.

- When an agent starts waiting for a slot, the waiter matches its permission mode as at a registration (a message
  between a bypassing session and one that is not is held) and puts its SendMessage `to` in the `espera_cupo` event.
- The line says `cupo de N lleno → SendMessage to=X «Espera tu turno»`, and the supervisa skill carries the text: finish
  the current step, leave the work consistent, start nothing new, and wait until «Ya es tu turno». Without a `to`, the
  supervisor asks the user to stop it in its pane. `lookout inicia` asks the same for the ones it leaves waiting.
- When its turn comes, after its note the supervisor sends «Ya es tu turno» to go on.
- `espera_cupo` wakes the supervisor (codex round 5: with the cupo full, nothing did). With a mode it could not match,
  the message is sent anyway and the user is asked to approve it while it is held; only without a `to` the user is
  asked whether to stop the agent in its pane.
- lookout's scripts cannot call SendMessage (a tool of the supervisor's Claude session): the waiter writes the line
  with the `to`, and the supervisor sends the message, as with every other note of lookout.
- `lookout inicia` asks the message again for the ones that were already waiting under the previous supervisor
  (codex round 4); with a herdr list it cannot trust, a queued one is never admitted, only new ones up to the free
  slots left after the queue.
- The line puts what to do and the `to` first and the tab after it, cut to the room left in the line: the digest clips at 160, and a
  long tab cut the `to` (adversary round 1). That line is never clipped itself: nothing bounds a session's name
  (codex round 1). `lookout inicia` with a herdr list it cannot trust adds the ones left
  out at the end of the queue and warns them too. It is a message, not a forced pause: the skill says so.

## 0.13.35

A decision about an agent that is still open when its «Como retomar» arrives now attends that block (p-5e02bc8cf9).
3-tier-memory, 2026-10-19: the supervisor opened d183 at 09:06:45 («¿Tecleo «aprobado» para A? (p-0ccd79fe36)»,
`--agentes cambio-worktrees`); the agent's idle at 09:07:05 carried a vigente block for that same pendiente, and the user
answered at 09:19:47. Only a decision opened after the block counted, so for 13 min the digest said «bloque vigente →
lookout relevo» of an agent that waited for the user's answer. With 0.13.32's 30-min notice a longer modal would have
sent the user a false «espera su relevo»: d205 (hook-para-checkpoint, opened 10 s before its block, answered 40 min
later) was one.

- `heuristicas.bloque_sin_atender`: a decision naming the agent attends the block when it is still open at the block's
  time or was answered after it (opened after it, as before, too). One answered before the block does not.
- Replayed on every real block of 3-tier: three change (d96, d129, d205), each a modal opened 10-60 s before the block
  and answered after it.
- `avisa_bloques` (p-625b4aa422, Sonnet's MINOR on 0.13.32): a modal naming the agent opened after the first idle with
  the block and answered before a later idle re-carried it already put that block before the user; the 30-min notice
  compared it with the last idle and said «ni abrió un modal después», which was false. The notice now compares with
  the first idle of the bloque_id. The digest row still compares with the last idle, so a block re-carried after the
  answer stays in front of the supervisor.
- `deliver.user_texts` (p-da8bbd7dc2, Sonnet's MINOR on 0.13.15): one line of broken UTF-8 in a transcript raised
  UnicodeDecodeError, and that read runs on every first send, so the delivery failed. It reads with replacement
  characters now, and so do the other four transcript readers with the same strict read (`retomar.ultimo_turno`,
  `relevo.assistant_texts`, `heuristicas.reporte_del_agente`, `gobierno.read_items`; adversary round 3): retomar,
  retiro and relevo failed on one broken byte too.
- `aprueba.explica_destino` (p-4c46390c7d, Sonnet r3 on 0.13.16): it printed «remote «origin» → «url»», and
  `nombra_destino` refuses any «» other than the command and the URLs, so a supervisor that copied the line as given
  was refused. The remote's name goes without «» now: «remote origin → «url»».
- The publication queue («Siguiente en la cola: …») and `lookout puerto` named the agent by lookout's name next to
  «SendMessage» (p-561f1a2173). After a relief or a /rename SendMessage does not take that name (0.13.24); both give
  the session's `to` now, as `inicia` and `corrige` do, and so does the digest line of a long background wait
  («pídele por SendMessage (to=…)», adversary round 5).
- `lookout aprueba`: the NO for a newer request said «aunque sea el mismo comando» for another command too
  (p-7730a9d0e2, live 2026-10-17). It says «con el mismo comando» or «otro comando: «…»» now.
- `lookout lanza`: when herdr did not start the agent at all (`agent_name_taken`, `agent_pane_busy` after the
  retries), the workspace lanza had created for it on the main checkout stayed open and empty (p-9a9ef79ced, live
  2026-10-18: w25). It is closed now. A start without SessionStart keeps it (a Claude may be on screen), and a
  worktree's workspace keeps it (it holds the folder). The pendientes skill and docs/plan.md say so (codex, pre-push round).

## 0.13.34

A supervisor watches at most 10 agents at a time (user's decision 2026-10-19). Past that a human cannot answer the
supervisor, and every Claude takes memory. An external user supervised 17. It lost its subscription access then, but
that was a billing error, not usage: this account ran 1 301 calls in one hour, with up to 28 sessions calling within the same 10 minutes, without a cut.

- The waiter registers a session it finds only while there is a free slot (`LOOKOUT_CUPO`, 10 by default). A slot is
  held by a registered agent alive in herdr, or one lookout is starting; a retired or relieved one holds none.
- The rest wait in `registry.json` → `espera_cupo`, in the order they were queued: no note, no rename, no mode match. Each one gets one
  `espera_cupo` line («espera turno … sigue en su pane sin supervisor»), and `resumen` shows `CUPO: 10, lleno en la
  última pasada · k esperan turno (…)` while someone waits. lookout does not pause a waiting agent: it keeps working, only unsupervised.
- When a slot frees, the next pass registers the first of the queue still alive (`le tocó su turno del cupo`). One
  gone from herdr leaves the queue.
- A pass trusts herdr's agent list only when it is not empty and shows the supervisor itself. A failed `herdr agent
  list` answers nothing, and the queue was emptied and re-queued in another order with a second `espera_cupo` line
  (adversary round 1).
- `lookout inicia` goes through the same cupo: before, it registered every agent it found (codex round 1: 12 of 12).
  It prints a `CUPO:` line with the ones left waiting. With a herdr list it cannot trust it
  counts every registered agent as alive and leaves the queue alone.
- `lookout pendientes`/`lanza`: the batch cap (3, `LOOKOUT_TOPE` or `--tope`) never passes the cupo. relevo and
  retoma swap one agent for another and do not go through it.

## 0.13.33

A user outside our setup saw many «Held message from another session … permission mode class doesn't match» between
supervisor-POS_MEGAMAYOREO and its agents (2026-10-19). Claude Code holds a message between a session that bypasses
permission prompts and one that does not, in both directions, and drops it after 5 min unanswered: the agent kept
waiting for an answer that never came.

- `lookout lanza` starts each agent in the supervisor's own mode (`--permission-mode`). Before, it passed none, and
  an agent took the user's default mode whatever the supervisor ran in. A supervisor in bypass does not start
  bypassing agents on its own: `lookout pendientes` prints a `MODO:` line and the batch modal asks the user;
  `lookout lanza … --bypass` only on that answer. A supervisor in plan, or one whose mode can't be read, passes none.
- An agent registered (`lookout inicia`, or found by the waiter) that bypasses while the supervisor does not is moved
  with Shift+Tab through herdr, its footer read after each press, until a prompting mode that is not plan (at most 6
  presses; none while it waits on a dialog or when its footer can't be read). Measured on a real session started with
  `--dangerously-skip-permissions`: one press took it to auto; a message from the supervisor sent before the press
  was held, another sent after it was delivered. Only the last lines of the screen count as its footer.
- When it can't be matched (the supervisor bypasses, or the agent did not move), the agent's registration line says
  `MODO DISTINTO → díselo al usuario`, and the skill says what to offer: lower the supervisor with Shift+Tab, or
  approve each held message. lookout never moves a running agent up to bypass (a relief keeps the old agent's mode); only `lanza --bypass`
  starts a new one there, on the user's answer.

## 0.13.32

Audit of the supervisor in 3-tier-memory (2026-10-19). It did ask every supervised agent for its `/checkpoint-3t`
and relieved them; two finished agents still sat unseen.

- An agent that closed its goalspec run stays in «Listo para revisar» after later turns without markers (a reply to
  the supervisor, a background task's turn). Before, the next turn put it back in «Idle»:
  decisiones-pendientes-bloqueadas was «listo» at 08:45:03 and «idle» at 08:45:08, and the digest hid it in
  «+2 agentes más» while its last turn asked the user to merge PR #40. A later goalspec verdict without a close
  takes it out (a new run). The user gets the «está listo para revisar» notification once, from the turn that
  closed the run, not again on each reply.
- A vigente or ambiguo «Como retomar» still unattended 30 min after it was left (no relief, no modal that names the
  agent, no new work) sends the user one herdr notification per block, from the checker pass. The block is its id:
  later replies that carry the same block again do not announce it again, and its 30 min count from the first turn
  that left it. Before, lookout sent
  none for a block because the supervisor attends it. pendientes-en-sessionstart's block was on every digest as
  «→ lookout relevo» for ~15 h; the supervisor told the agent to stay still and asked the user in prose.
- The digest row of a vigente block and the skill say it: relieve it, or open a modal with `--agentes`. Holding the
  agent with a question in prose is not an option.

## 0.13.31

- `lookout entrega --pasos reload` confirms the /reload-plugins the way `lookout recarga` has since 0.13.24: by the new
  `local_command` row of /reload-plugins in the agent's transcript, and by the screen only when lookout finds no
  transcript (p-231e8eeb51). Before, it waited with `herdr pane wait-output --match Reloaded:`, which searches the
  screen as it already is: an older «Reloaded:» still on screen gave `reload: ok` before the new one appeared, and
  `reload: ok` was printed even when herdr had not typed the command. Both commands now share one reader
  (`recarga.teclea`). The output says where it looked: `reload: ok (vi «Reloaded:» en su transcript)`,
  `reload: sin confirmar: …`, or `reload: NO: herdr no tecleó /reload-plugins …`. The wait is still 15 s.

## 0.13.30

Built as 0.13.28, never published under that number (0.13.29 went out first).

Four defects found in the live run of 2026-10-18 (p-97fe1fe744). The run used the installed 0.13.26: `lookout
pendientes` on claude-vzert, and a real supervisor with real agents in herdr on a test repo.

- `hará:` of a code task on the main checkout says what that agent does. Before, every such task showed the same
  240 characters of the template's rules, cut before they said the agent does not commit. The scope's first sentence
  now says «Cambias código en el checkout principal … sin commit: el commit lo hace el usuario». `hará:` shows that
  sentence followed by the files the pendiente cites.
- A tag in brackets in front of a pendiente no longer hides its type («**[Victor] Avisar a los devs…**», claude-vzert:
  it came out `codigo`, with edit tools; now `comunicacion`). A verb inside the brackets still counts as the verb:
  «[Rotar] token de acceso» stays `credencial`, «[Fix] Medir…» stays `codigo`, and «[Publicar]…» keeps its high risk.
  The text with the tag's word decides when one of the classifier's rules matches it, otherwise the text after the
  tag; the risk is high if either reading is. A label in front of a known verb («[P1] Medir…») now reads as that verb.
  Doubled brackets («[[P1]]») and several tags in a row («[P1] [Victor] …») are read the same way.
- `lookout lanza` retries `agent start` while the pane of the new workspace is not a shell yet (`agent_pane_busy`;
  up to 5 times, 2 s apart). Before, the first agent of the batch failed this way, and lookout waited 60 s and said
  «no llegó el SessionStart … (¿cargó el plugin?)». A start that herdr refused (`agent_pane_busy` after the retries,
  `agent_name_taken`) now fails at once, with herdr's error.
- After a failed start and its retry, the two registry entries share a name. Lookup by name now gives the live
  retry, not the failed one. Before, the supervisor typed into the failed start's dead pane, and `libera --fallida`
  acted on the old entry. A new launch of the same task also retires a start of that task that never ran (no
  SessionStart, or refused by herdr), so `resumen` lists the agent once. A code agent that ran and then failed keeps
  its entry, as before.

## 0.13.29

- An agent with a live background shell can take input again after `lookout recarga` (p-ad978476a5). Bench 2026-10-18
  with 0.13.26: after a reload of an agent herdr saw `working` only because of its shell, `envia` said «NO ENTREGADO:
  está working». `/reload-plugins` writes after the Stop a `user` row «<local-command-caveat>» (isMeta), a `user` row
  with only its `<command-name>`/`<command-message>`/`<command-args>` and a `system` row `local_command`, and the quiet
  check of 0.13.10 took the two `user` rows for a turn, so `envia`, `entrega`, `relevo`, `cierra-pestana` and the
  sweep refused that agent until another turn ended (never, for a shell that does not end). Now a local command counts
  as quiet only as that whole set: the command row, its isMeta caveat right before or after it, and its
  `local_command` right after it (caveats in between allowed). A skill typed in the box (no `local_command`), a
  command still running (no `local_command` yet), a command and its output with no caveat, a lone caveat, a caveat
  that is not isMeta and a command row with any other text stay a turn. The supervisa skill and docs/plan.md say so.
  Replayed on the bench transcript: refused before, quiet after.

## 0.13.27

- `lookout publica` in PR mode (p-ca286da56c). In 3-tier-memory (2026-10-17/18) every agent published through a
  branch and a pull request that the user merges, and the queue assumed a push to main: LISTA ordered
  `git push origin HEAD:main`, `--hecho` said NO after a branch push + PR (#39, #42), branches behind main got
  BASE-MOVIDA, publications expired before the merge, and supervisor.md said «cola: vacía» with 5 PRs open.
  - `lookout publica <proyecto> --modo pr|directo` keeps the mode in publicaciones.json (directo by default; nothing
    changes for a project that never sets it).
  - In PR mode the check runs on the agent's own branch: no fast-forward over main (a line says how far behind it is),
    commits, version and private paths read from where the branch leaves main, a version above origin's
    (VERSION-VIEJA) that follows the merge order: above every PR before it and below every PR after it, never equal
    to another (VERSION-USADA). A branch that touches no version file claims no version, as in direct mode. An open
    PR checked again after new commits (a review fix) is not its own rival: `--hecho --pr N` replaces its old entry
    and keeps its place in the merge order. NO also for an agent on the main branch (SIN-RAMA),
    a main tip this tree never fetched (BASE-DESCONOCIDA) or a remote branch the push could only force (RAMA-DIVERGE).
    LISTA orders `git push origin HEAD:refs/heads/<rama>`; the supervisor is told the `gh pr create` that follows.
  - `--hecho --pr N` checks origin/<rama> is the verified head and reads the PR with gh (same branch, head and base):
    open → `pr-abierto`, already merged → `publicada`. A gh that fails is a NO, without a traceback.
  - A `pr-abierto` does not hold the next agent (the queue moves to the merge), never expires with its session, a
    relief or a closed tab, and is read again by concilia (at most once a minute per PR): MERGED → `publicada`, with a
    warning when an earlier PR is still open (out of order); CLOSED → `caducada`; a gh error leaves the PR open and
    it is read again a minute later. A
    `lista` whose branch is already on origin stays `lista` in PR mode (only the merge publishes).
  - The queue, the resumen and supervisor.md show each open PR with its number and its place in the merge order (the
    order its publication was verified).
  - `lookout publica <proyecto> --fusiona N --decision dK [--fuera-de-orden]`: the supervisor merges an open PR of the
    queue when the user said yes in its modal. dK must be a plain decision opened with `--si-es`, closed by the
    modal's hook with that exact choice (a `decision --cierra … --si` the supervisor typed does not count), name `#N`
    and not have been used (it is marked used before the merge); the PR must still be on the verified head (also
    passed as `--match-head-commit`), branch and base, mergeable with merge state CLEAN, every check finished green
    (a PR without checks merges and says so), and first in merge order unless `--fuera-de-orden`. Merge commit only: squash or rebase would leave the
    agent's commits outside main, which `cierra` reads as not published.

## 0.13.26

- The two findings of round 3 of the adversarial review (codex break, Sonnet hold, 2026-10-18), after which the user
  chose to close the review: `chrt` options that take a value (`-T`, `-P`, `-D` and their long forms) no longer hide
  the command (`chrt -d -T 100000 -P 200000 0 pkill -f claude` is denied), and the `\;`, `';'` or `";"` that ends a
  `find -exec` is kept as one word, so `find . -exec sh -c "pkill -f claude" \;` is judged as the `sh -c` it runs.
  A `\;` outside `find` is a literal argument, not a separator, as in bash. Still not covered (pendiente
  p-4f3fe84d89): a kill inside a quoted string that another program runs (`xargs -I{} sh -c "pkill -f {}"`,
  `watch "pkill -f claude"`), and sessions lookout did not register.

## 0.13.25

- Findings of round 2 of the adversarial review of 0.13.23 (Sonnet and codex break, 2026-10-18; 0.13.24 is another
  session's, on its own branch):
  - `xargs -I{} pkill {}` passed the brake: the subshell scanner turns `{}` into a separator, so `xargs` and `pkill`
    fell into two commands. `{}` is now kept as a word before the scanner runs.
  - `env -S "<command>"` / `--split-string` is read as the command it runs; `env -P <dir>`, `coproc`, and the
    wrappers of the notes (`setsid`, `ionice`, `chrt` with its priority, `doas`, `watch`) are looked through; a
    `find -exec`/`-execdir`/`-ok`/`-okdir` command is judged as a command of its own.
  - A falsy command that is not text (`None`, `[]`, `0`, `False`, `{}`) is denied as unreadable; before, it became an
    empty command and passed. An empty string still passes.
  - `ramas_destino` falls back to `<remote>/main` and `<remote>/master` also when the remote's HEAD names a branch that
    is gone; before, it returned nothing and every commit counted as unpushed.

## 0.13.24

- The name SendMessage takes for an agent (p-e9c8601cfb). After a relief or a `/rename` an agent's session can have
  another name than lookout's: in 3-tier (2026-10-17) to=cambio-worktrees gave «No agent named» (the session was
  cambio-worktrees-2) and to=correccion-snipet-de-cierre «not reachable» (the session had renamed itself). lookout now
  reads each live session's name from Claude Code's `<config>/sessions/<pid>.json` (a file whose process is gone, that
  has no `procStart`, or whose pid now belongs to a process started at another time, counts as none): `inicia` prints it in a `to (SendMessage)` column (`to desconocido` when it is not there), `resumen` adds
  `[to=…]` to a row whose session name differs from lookout's, and the supervisor's relief notice and `corrige` name it.
  The supervisa skill says to use that `to`.
- `lookout recarga` no longer says «sin confirmar» after a reload that happened (p-eff2c277ba). Measured: in 3-tier
  13 of 40 calls said it, and in all 13 the agent's transcript has its /reload-plugins `local_command` row «Reloaded: …»
  written when lookout typed it, inside the 10 s wait. The defect was the screen count: `agent read --source recent` of
  a Claude Code pane gives only its visible rows, so on a screen full of «Reloaded:» lines a new one pushes an old one
  out and the count stays. On a test agent (2026-10-18) all 20 reloads left their transcript row and the screen count
  missed 5: 3 on a full screen, 1 read herdr refused while the agent answered a message typed into it, and 1 after that
  answer redrew the screen with fewer «Reloaded:» lines. Neither the 10 s wait nor a lost Enter was the cause. With a
  transcript, only its new row confirms the reload now (a `local_command` row whose `commandRun` is reload-plugins); the screen count is used only when lookout finds no transcript,
  and the message says which one it read. A prompt herdr did not type is said, not waited for. Nothing is typed twice.

## 0.13.23

- Findings of the adversarial review of 0.13.18 and 0.13.22 (codex break, Sonnet hold with notes, 2026-10-18):
  - The pkill brake now looks through wrappers and shell keywords before judging the command: `timeout`, `nice`,
    `env` (with -i, -u and assignments), `stdbuf`, `nohup`, `exec`, `command`, `time`, `sudo`, `xargs`, `then`, `do`,
    `else`, `if`, `while`, `until`, and `eval`'s words. A `pkill` or `killall` whose arguments come from `xargs` is
    denied (they are not in the text), and so is a `kill` fed by `xargs` unless a `pgrep` of the same line gives its
    pids (that `pgrep` is judged like a `pkill`).
  - A command the brake cannot read (not text, or an error inside the brake) is denied; before, `main()` turned the
    exception into no output, which lets the command run.
  - `cierra-pestana` counts a commit as upstream only when its patch is on the remote's main branch (its HEAD, else
    main or master) or on the branch's upstream; 0.13.22 took any remote ref, so the same patch on an unrelated branch
    let a tab close. The live 3-tier commits still give 3 upstream and 3 rebased copies (against origin/main).
  - The supervisa skill says what to do with «copia rebasada»: compare with `git range-diff`, ask the user with
    `lookout decision … --si-es`, act only on that choice, then repeat `cierra-pestana`; never move the branch itself.

## 0.13.22

- `cierra-pestana` no longer blames an agent for commits that are already upstream. Live (3-tier, 2026-10-17 17:05),
  it refused to close pendientes-sin-id for «6 commit(s) suyo(s) sin subir»: they were the 2.58.1 commits its first
  session (900f49bf, 2026-10-14, before its current task) left on the old branch reopen-replay-ts, whose content had
  reached main through a rebased PR. Before counting, lookout now compares the unpushed commits with every remote ref
  of the 30 days before the oldest: one whose patch is there (`git patch-id --stable`) does not count; one with a copy
  of the same subject and author but another patch (a rebase that resolved a conflict) blocks as «copia rebasada»,
  with both hashes, `git range-diff` and the branch to ask the user about, not as the agent's work; and one made only
  by an earlier session of its chain stays its own (its chain's work to push, as since 0.13.2) and names that session
  and the commits' dates. On the live commits this gives
  exactly what `git cherry` gives: 3 upstream, 3 rebased copies. If git takes more than 30 s it falls back to the old
  count.

## 0.13.21

- `lookout decision … --cierra dN` on a decision that is already answered says so. Live (3-tier, 2026-10-17), the
  vigía's test modals d125 and d126 named no decision, so the hook opened each as its own entry and closed it with the
  user's answer («Listo»), with no yes or no. The supervisor then tried `--cierra d125` and got «No hay una decisión
  abierta d125.» (rc 5), which read as if it did not exist. Now an answered decision prints how it was answered and its
  answer (rc 0, nothing rewritten), an unknown id says it does not exist (rc 5), and supervisor.md shows an answer with
  no yes or no as «respondió, sin sí ni no (no autoriza nada)» instead of a bare «respondió».

## 0.13.20

- `lookout retoma PROYECTO AGENTE`: an agent whose session ended without anyone asking (SessionEnd «other», not a
  `/exit`) starts again with `claude --resume <sid>`, its context intact. Live (3-tier, 2026-10-17 22:42), a stray
  `pkill … -n` killed three reliefs; their panes stayed at a shell prompt, but they left the digest table, `relevo`
  needs the session alive, `lanza` only opens new agents, and the supervisor asked the user to type `claude --resume`
  by hand. `--resume` keeps the session id (measured the next morning: SessionStart with source «resume» and the same
  id), so its marker, registry entry and task still hold. `retoma` runs it in its own pane when that pane is at a shell
  prompt in the session's folder (another live session there, or another folder: NO with the reason), or opens a new
  tab on that folder when the pane is gone; with the name, system prompt file, model, effort and permission mode it ran
  with (from the registry, else its transcript; one missing: NO). Its trigger says when and why it ended, that its
  background work died with it, and asks for 3 lines to the supervisor. Not for a relieved, closed or failed-relief
  agent (`relevo` repeats that one), nor when its transcript lives under another folder than its registered one
  (`--resume` would not find it). A start that fails leaves `retoma-fallida`, not `fallida`, so `lookout pendientes`
  does not launch a new agent for its task while the digest still asks to resume it. It does not look at the session
  cap: it gives back a slot the agent already had. `lote.arranca` takes `resume=True` for it.
- The digest keeps such an agent in «Te necesita» on every wake: «salió sin que nadie lo pidiera HH:MM (SessionEnd
  «other») → `lookout retoma P agente`; tú, no el usuario». The supervisa skill says the same. A live supervisor that
  already read the skill needs `/lookout:supervisa` again after `/reload-plugins` to see it (rule 6); the digest row
  reaches it without that. Entering «Te necesita» notifies like any other agent there: a killed agent now wakes the
  waiter and shows a herdr notification.

## 0.13.19

- «hooks viejos» counts the reload lookout typed. Live (3-tier, 2026-10-16/17), prompts-repetidos stayed idle for 22 h
  with no hook event, the last one written by hooks older than 0.13.8. The supervisor reloaded it 4 times with
  «Reloaded:» on screen, and each time lookout was updated again the row came back as «lookout <0.13.8», the version of
  that old event: the reload looked useless and the supervisor reloaded in a loop. A reload loads what was installed
  then (`recargado`), so the row now takes the newer of that and the last event's version (also for the plugins its
  hooks cite), and says «ya recargado; la X llegó después» when only a later update makes it old again.

## 0.13.18

- A brake on killing processes by name. Live (3-tier, 2026-10-17 22:42:47), a subagent ran
  `pkill -f "tools/run-tests.sh" -n`: macOS's pkill stops reading options at the first pattern, so `-n` was a second
  pattern and every process with "-n" in its command line got SIGTERM, including the three reliefs lookout had started
  with `claude … -n <nombre>` and three test suites. The PreToolUse[Bash] hook now denies, for every registered agent
  (and its subagents) in every mode, before anything runs: an option after the pattern of `pkill` or `pgrep`; a
  `pkill` or `killall` pattern that matches a Claude session as lookout starts it, herdr, lookout's waiter or a shell
  (`claude`, `session-id`, `lookout`, `bash`, `.`, the user's home…), judged on samples built with this machine's real
  paths, not on the live process list; the same for a `pgrep` in a command that also runs `kill` or `xargs`
  (`kill $(pgrep -f claude)`); a pattern built at run time or that is not a valid regex; and `kill -1`. Also inside
  `sh -c '…'`, subshells and after `sudo`. Subagents' hooks arrive with their parent's session id (measured in 3-tier:
  27 events of commands only subagents ran), so they are covered. The reason tells the agent to look with `pgrep -lf`
  and kill by pid. A lone `pgrep` with a broad pattern still passes (a read). Not covered: a session lookout did not
  register (the supervisor, an agent started by hand) until it is registered, and `pkill` behind `timeout`, `nice`,
  `xargs` or `env -i`. Live agents get it after `lookout recarga`.

## 0.13.17

- `lookout relevo --retomar` says it takes the path of a file. Live (3-tier, 2026-10-17), the help showed only
  `--retomar RETOMAR`, the supervisor passed the «Como retomar» text itself, and lookout died with a
  FileNotFoundError traceback. The help now reads `--retomar ARCHIVO` with what the file holds, and a value that is
  not a readable file (missing, a folder, not UTF-8) is refused with one line that says what it wants (rc 2),
  before the lock or the agent are looked at.

## 0.13.16

- The question of a `lookout decision --permiso` names where an agent's `git push` really goes, as lookout read it.
  Live (2026-10-17), with a local test remote, the supervisor wrote «a GitHub» and «no se puede deshacer limpio» in
  its modal, and the user's yes rested on that text. The PermissionRequest hook now keeps the agent's cwd in the
  `blocked` event; `decision --permiso` reads in that repo the remote the push goes to (the repository argument or
  `--repo`, else `branch.<b>.pushRemote`, `remote.pushDefault`, `branch.<b>.remote`, `origin`, after any `git -C`) and
  its push URLs as `git remote get-url --push --all` gives them, and prints them. The question must show each URL
  exactly, between «», with no other «…» than the command and those URLs and nothing else in it shaped like a URL
  (`scheme://`, `user@host:`, `host.tld:` or `host.tld/`, `www.`), or the decision does not open; `lookout aprueba` checks it again on the question the user
  answered and presses nothing without it. A URL or a path given as the repository is shown as given (a path made
  absolute); the user and password of an http(s) URL are shown as `***`. When lookout cannot read the destination it
  says why, and the question must say «destino desconocido», between «», under the same rule (no other «…» than the
  command, nothing shaped like a URL): a
  command the shell would expand or chain, a push behind another program (`timeout`, `sudo`, `bash -c`, a path to
  git) or behind environment variables, a global git option other than `-C`, a name that is not a remote, a literal
  URL in a repo that rewrites URLs, a detached HEAD with no repository given, or an event without cwd (written before
  this version). Only `git push` has a destination; other commands are as before. Tests:
  tests/test_lookout_01316.py, with real repos.

## 0.13.15

- A retry of `lookout entrega` (and of the trigger an alta or a relief types) recognises a typed `/command` already in
  the transcript. When the `working` event of the first attempt was lost, the retry reads the session's transcript to
  see whether the text arrived; Claude Code does not keep a typed `/command` as typed but as a block of tags
  (`<command-name>`, `<command-args>`, often `<command-message>`), so a relief typed with `--goalspec` could get its
  `/goalspec:goalspec <trigger>` typed a second time. The retry now reads such a block back as `/name args`. Measured on
  2026-10-17 over the transcripts in `~/.claude/projects` (about 5100 files and 1380 blocks; the count moves as
  sessions are written and removed): name and message come in either order, `<command-args>` comes last when there
  are args, is not escaped (args may hold its own closing tag), and can be empty, missing or span lines; every block
  read back as a `/command`. A message that holds such tags among other text is not a command, another command or
  other args do not count, and a malformed block is read in linear time. A text already in the transcript before
  the first attempt (the same `/command`, or the same plain text, sent earlier in that session) no longer confirms a
  retry: until now only a `! command` was counted that way. The tests run the real delivery against the herdr stub
  with the block in the transcript and no event (tests/test_lookout_01315.py).

## 0.13.14

- supervisor.md (its pending decisions and its «Proximo paso» line), the digest and the supervisor's Stop reminder show
  the exact label of each open decision's modal option, before its question:
  `[modal: sí = «…»]` for a `--si-es` decision, `[modal: parar = «…», dejar = «…»]` for a `--shells-parar/--shells-dejar`
  one. The modal's hook closes such a decision from the user's literal choice, and any other label counts as no; a
  supervisor picking up an open decision after a relief or a compaction saw only the question and had to read
  decisiones.json for the label (codex r11 on 0887ded). The label is never clipped (a newline in it shows as `\n`):
  the digest clips only the question to its 160 columns, and the line that folds the decisions past the fifth names
  each one's id and labels.

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
