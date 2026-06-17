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

## Multi-tool: Codex

Set `codex = true` under `[sources]` in `~/.totalrecall/config.toml` to also learn from
OpenAI Codex CLI sessions (`~/.codex/sessions/.../rollout-*.jsonl`). Codex has no SessionEnd
hook, so its sessions are picked up by `reconcile` — i.e. the next time any `totalrecall worker`
runs (after a Claude Code session ends, or manually). To analyze Codex history immediately,
run `totalrecall reconcile` then `totalrecall worker`. Friction from Codex sessions appears in
`insights.md` with `tool=codex` evidence, in the same pattern library as Claude Code.
