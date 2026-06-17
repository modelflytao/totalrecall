# TotalRecall

Learns from your AI-coding sessions: after each Claude Code session ends, it extracts
*collaboration friction* (repeated corrections, misunderstandings, rework, tool errors)
and maintains a living `~/.totalrecall/insights.md`.

## Install

```
pip install -e .
totalrecall init      # scaffolds ~/.totalrecall and installs the SessionEnd hook
```

## How it works

SessionEnd hook → enqueue → detached `worker` → adapter → deterministic events +
`claude -p` semantic analysis → merge into pattern library → re-render `insights.md`.
Self-produced analysis sessions are excluded; crashed sessions are caught by `reconcile`.

## Commands

`init` · `worker` · `reconcile` · `synth` · `status` · `retry` · `ingest <path>`

## Config

`~/.totalrecall/config.toml` — models (default Sonnet), synth cadence, catalog top-K, sources.

Phase 1 = insights only.

## Phase 2 — rule proposals (closed loop)

`totalrecall propose` drafts CLAUDE.md rules from your top recurring friction →
review `~/.totalrecall/proposals.md` → `totalrecall apply <id…>` writes them to a
managed `~/.claude/totalrecall-rules.md` (`@`-imported once into CLAUDE.md, backed up).
The verifier then marks each applied pattern **resolved** (no recurrence in N days) or
**ineffective** (recurs after apply) — shown in `insights.md`. `totalrecall reject <id…>`
declines a draft. Commands: `propose` · `apply` · `reject` · `proposals`.
