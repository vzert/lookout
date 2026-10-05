# lookout — a supervisor for the coding agents of one project

lookout is a [Claude Code](https://claude.com/claude-code) plugin. It turns one Claude Code session into the
**supervisor** of the other Claude Code agents that work on the same project, each in its own
[herdr](https://herdr.dev) pane.

The supervisor coordinates. It never does the agents' work. It:

- finds the agents of one project (the main checkout and its git worktrees), registers them and gives each one a name;
- receives their questions by `SendMessage`, answers what is reversible, and asks you about what is not
  (push, merge, deletes, anything that leaves the machine);
- reads its state from files and hook events, not from the screen, and wakes only when something happens;
- with `/lookout:pendientes`, launches up to 3 open pendientes of a
  [3-tier memory](https://github.com/vzert/3-tier-memory) project, one agent per item, each in its own worktree;
- before a push, reads the [goalspec](https://github.com/vzert/goal-forge) adversary verdict in the agent's own
  transcript, then publishes in order, one agent at a time;
- spots a stuck agent (the same error again and again, no progress, a usage-limit pause) by checking more than one
  signal, and stops correcting after 2 tries.

The plugin talks to you and to the agents in **Spanish**.

## Requirements

| What | Version | Why |
|---|---|---|
| Claude Code | 2.1.x with plugins (tested on 2.1.289) | runs the supervisor and the agents |
| herdr | **0.9.1 or newer**, client and server compatible | the panes the agents run in |
| Python 3, git, bash | any recent | the `lookout` command and its hooks |
| macOS or Linux | | CI runs on both |

`/lookout:supervisa` checks herdr before it does anything. If herdr is missing, older than 0.9.1, its server is not
running, or the client and the server are not compatible, the supervisor refuses to start (`NO ARRANCO`) and tells
you why. It takes no lock and touches no agent.

## Install

```bash
claude plugin marketplace add vzert/lookout
claude plugin install lookout@lookout-marketplace
```

lookout has its own marketplace. Installing or updating it never changes goalspec or 3-tier memory, and their
updates never change lookout.

### With goalspec and 3-tier memory (recommended)

Each plugin comes from its own marketplace:

```bash
claude plugin marketplace add vzert/goal-forge
claude plugin install goalspec@goal-forge

claude plugin marketplace add vzert/3-tier-memory
claude plugin install 3-tier-memory@3-tier-memory-marketplace
```

| Without | What happens |
|---|---|
| goalspec | `/lookout:supervisa` warns you and goes on. A push has no adversary verdict to check: `lookout gobierno` says `SIN-GOALSPEC`, and when the supervisor asks you about the push it tells you the push had **no independent review**. The task prompts of launched agents leave out the goalspec rules. |
| 3-tier memory | `/lookout:supervisa` works. `/lookout:pendientes` reads the project's `memory/_pendientes.md` if the project has one (the 3-tier format). Closing a pendiente (`lookout cierra`) writes through 3-tier's journal scripts: without them it refuses and says so. |

## Use

Start the agents of a project in herdr panes. Then, in one more Claude Code session (also in a herdr pane):

```
/lookout:supervisa /path/to/the/project
/lookout:pendientes /path/to/the/project
```

Agents that were already running when you installed lookout get `/reload-plugins` from the supervisor, so their
hooks are active.

### Tool permissions of the agents

By default every permission dialog of an agent stays with you. lookout can approve **one** call at a time for
trivial actions inside an agent's own worktree. It does this only in manual mode, never with "always allow", and only
after **you** turn the rules on. The supervisor shows the rules and where to turn them on with `lookout permisos`. The template is in
`plugins/lookout/rules/permisos.toml`. You copy it to `~/.config/lookout/permisos.toml` and set `activo = true`. The
supervisor never writes that file. Push, merge, publishing and deletes outside the worktree always go to you.

## Update

```bash
claude plugin marketplace update lookout-marketplace
claude plugin update lookout@lookout-marketplace
```

Claude Code keeps one copy of a plugin per version. Each release bumps the version in
`plugins/lookout/.claude-plugin/plugin.json` and in `.claude-plugin/marketplace.json` (`metadata.version`), and CI
fails if the two differ.

## Development

```bash
bash tools/run-tests.sh
```

It checks shell syntax, that the Python compiles, the manifests and the version rule, the skill frontmatter, and runs
the unit suite. herdr is replaced by a stub (`tests/fixtures/herdr_stub.py`), so the suite needs no running herdr.
The 2 closing tests need 3-tier's journal scripts. Set `LOOKOUT_3TIER_BIN` to its `bin/` folder, otherwise those
tests are skipped. CI (`.github/workflows/tests.yml`) runs the same script on Ubuntu and macOS.

Comments in the code cite design notes (`docs/plan.md`, `docs/herdr-notes.md`) that live in the private working
repo and are not published here.

## License

MIT, see [LICENSE](LICENSE). Credits: [CREDITS.md](CREDITS.md).
