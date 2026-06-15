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

Phase 1 = insights only. Phase 2 (planned) turns high-strength patterns into proposed
skill / CLAUDE.md / agent edits.
