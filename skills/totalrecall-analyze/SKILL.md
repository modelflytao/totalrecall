---
name: totalrecall-analyze
description: Analyze one normalized AI-coding session for collaboration friction, returning a JSON array of findings. Invoked headless by TotalRecall.
---

# TotalRecall — Session Friction Analyzer

You are given ONE normalized session (JSON) and a compact catalog of already-known
friction patterns. Detect **per-session friction instances** only. Do NOT judge whether
something is "recurring" — recurrence is computed downstream by accumulation.

## Input (provided in the prompt)
- `session`: { turns:[{idx,role,text,tool_name,tool_status}], events:[...], stats:{...} }
- `catalog`: [{ id, title, category, description }]  ← known patterns

## What to detect (categories)
- `misunderstood-intent` — assistant did X, user corrected to Y
- `repeated-correction` — user (re)states a constraint/preference (e.g. "use PowerShell not bash")
- `clarification-gap` — many back-and-forth turns before any action
- `rule-violation` — assistant broke a previously stated preference
- `tool-error` — notable failed tool use that caused rework
- `frustration` — explicit "that's wrong again" / visible frustration

## Reusing pattern ids (important)
For each finding, if it matches an existing catalog entry, set `pattern_id` to that
entry's `id`. Otherwise leave `pattern_id` null and propose a stable kebab-case `slug`.

## Output
Output ONLY a JSON array (no prose, no code fences). Each element:
```
{
  "category": "<one of the categories>",
  "description": "<one concise sentence>",
  "severity": <1-5>,
  "turn_refs": [<turn idx>, ...],
  "pattern_id": "<existing catalog id or null>",
  "slug": "<kebab-slug or null>",
  "phase2_hint": "<optional: concrete skill/CLAUDE.md/agent change, or null>"
}
```
If there is no friction, output `[]`.
