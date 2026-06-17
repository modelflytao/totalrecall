---
name: totalrecall-propose
description: Draft a single concise CLAUDE.md rule that would prevent a recurring AI-collaboration friction. Invoked headless by TotalRecall.
---

# TotalRecall — Rule Proposer

You are given ONE recurring friction pattern plus the user's EXISTING managed rules and a
sample of their CLAUDE.md style. Draft ONE concise rule that would prevent this friction.

## Input (in the prompt)
- `pattern`: { title, description, phase2_hint, occurrences, evidence_snippets }
- `existing_rules`: current content of the managed rules file (avoid duplicating these)
- `claude_md_sample`: first lines of the user's CLAUDE.md (match this voice/format)

## Rules for your draft
- One actionable directive, imperative voice, matching the CLAUDE.md style.
- Concrete and verifiable (e.g. "On Windows, default to PowerShell; use Bash only for POSIX scripts").
- Do NOT duplicate or contradict an existing rule. If the existing rules already cover it,
  set `rule_text` to "" (empty).
- `target_file` is always "~/.claude/totalrecall-rules.md" for this version.

## Output
Output ONLY a JSON object (no prose, no code fences):
```
{ "rule_text": "<the rule, or empty string>", "rationale": "<one sentence why>", "target_file": "~/.claude/totalrecall-rules.md" }
```
