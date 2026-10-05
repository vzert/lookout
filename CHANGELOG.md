# Changelog

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
