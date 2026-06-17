# TotalRecall Codex Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Analyze Codex CLI sessions (`~/.codex/sessions/.../rollout-*.jsonl`) through TotalRecall's existing pipeline, alongside Claude Code sessions.

**Architecture:** Add a `CodexAdapter` that parses Codex rollout JSONL into the same `NormalizedSession` shape; a path-based adapter dispatcher `adapters.for_path()`; make each adapter produce a *complete* session (move A-class event extraction into the Claude Code adapter so the worker just calls `for_path(p).parse(p)`); and extend `reconcile` to scan the Codex sessions dir when `sources.codex` is enabled.

**Tech Stack:** Python 3.11+ (stdlib `json`, `collections.Counter`, `datetime`), `pytest`. Builds on Phase 1+2 (100 tests green on `main`).

**Spec:** `docs/superpowers/specs/2026-06-17-totalrecall-codex-design.md`.

---

## File Structure

```
src/totalrecall/
  adapters/
    __init__.py        # MODIFY: add for_path(path) dispatcher
    codex.py           # NEW: CodexAdapter (rollout JSONL -> NormalizedSession, incl. events/stats)
    claude_code.py     # MODIFY: parse() now calls extract_events internally (self-complete)
  reconcile.py         # MODIFY: scan CC + Codex dirs per config.sources; add codex_sessions_dir()
  worker.py            # MODIFY: process_path uses adapters.for_path(p); drop extract_events call
tests/
  fixtures/codex_basic.jsonl   # NEW
  test_codex_adapter.py        # NEW
  test_adapters_dispatch.py    # NEW
  test_reconcile_codex.py      # NEW
```

Convention reminders (from Phase 1): tests use the `home` fixture (isolated `TOTALRECALL_HOME`); commit per task with two `-m` flags (no temp files → no BOM): `git commit -m "<subject>" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"`; run tests with `python -m pytest`.

---

## Task 1: CodexAdapter

**Files:**
- Create: `src/totalrecall/adapters/codex.py`
- Create: `tests/fixtures/codex_basic.jsonl`
- Test: `tests/test_codex_adapter.py`

- [ ] **Step 1: Write the fixture**

`tests/fixtures/codex_basic.jsonl` (ONE JSON object per line, exactly these 12 lines including the trailing garbage line):
```
{"timestamp":"2026-06-13T14:40:56Z","type":"session_meta","payload":{"id":"cdx-001","cwd":"D:/work/demo","cli_version":"1.0","base_instructions":"sys"}}
{"timestamp":"2026-06-13T14:41:00Z","type":"response_item","payload":{"type":"message","role":"user","content":[{"type":"input_text","text":"use PowerShell not bash"}]}}
{"timestamp":"2026-06-13T14:41:05Z","type":"response_item","payload":{"type":"message","role":"assistant","content":[{"type":"output_text","text":"ok using PowerShell"}]}}
{"timestamp":"2026-06-13T14:41:06Z","type":"response_item","payload":{"type":"function_call","name":"shell","arguments":"{\"command\":\"ls\"}","call_id":"c1"}}
{"timestamp":"2026-06-13T14:41:07Z","type":"response_item","payload":{"type":"function_call_output","call_id":"c1","output":"a.py b.py"}}
{"timestamp":"2026-06-13T14:41:08Z","type":"response_item","payload":{"type":"message","role":"developer","content":[{"type":"input_text","text":"system note"}]}}
{"timestamp":"2026-06-13T14:41:10Z","type":"response_item","payload":{"type":"patch_apply_end","call_id":"c2","success":true,"status":"completed","changes":{"D:/work/demo/a.py":{"type":"update","content":"x"}}}}
{"timestamp":"2026-06-13T14:41:11Z","type":"response_item","payload":{"type":"patch_apply_end","call_id":"c3","success":true,"status":"completed","changes":{"D:/work/demo/a.py":{"type":"update","content":"y"}}}}
{"timestamp":"2026-06-13T14:41:12Z","type":"response_item","payload":{"type":"patch_apply_end","call_id":"c4","success":true,"status":"completed","changes":{"D:/work/demo/a.py":{"type":"update","content":"z"}}}}
{"timestamp":"2026-06-13T14:41:13Z","type":"response_item","payload":{"type":"patch_apply_end","call_id":"c5","success":false,"status":"failed","changes":{"D:/work/demo/b.py":{"type":"update","content":"w"}}}}
{"timestamp":"2026-06-13T14:41:20Z","type":"event_msg","payload":{"type":"turn_aborted","turn_id":"t1","reason":"user_interrupt"}}
not-json-garbage
```

- [ ] **Step 2: Write the failing test**

`tests/test_codex_adapter.py`:
```python
from pathlib import Path
from totalrecall.adapters.codex import CodexAdapter

FIX = Path(__file__).parent / "fixtures"

def _parse():
    return CodexAdapter().parse(FIX / "codex_basic.jsonl")

def test_session_meta_fields():
    s = _parse()
    assert s.tool == "codex"
    assert s.session_id == "cdx-001"
    assert s.cwd == "D:/work/demo"
    assert s.git_branch is None
    assert s.is_analysis_session is False
    assert s.started_at == "2026-06-13T14:40:56Z"
    assert s.ended_at == "2026-06-13T14:41:20Z"

def test_turns_roles_and_developer_skipped():
    s = _parse()
    roles = [t.role for t in s.turns]
    assert roles == ["user", "assistant", "tool"]      # developer skipped
    user = [t for t in s.turns if t.role == "user"][0]
    assert user.text == "use PowerShell not bash"
    tool = [t for t in s.turns if t.role == "tool"][0]
    assert tool.tool_name == "shell"

def test_events_edit_churn_toolerror_interrupt():
    s = _parse()
    kinds = {e.kind for e in s.events}
    assert "churn" in kinds and "tool_error" in kinds and "interrupt" in kinds
    churn = [e for e in s.events if e.kind == "churn"]
    assert churn[0].ref == "D:/work/demo/a.py"          # a.py edited 3x
    assert any(e.kind == "interrupt" for e in s.events)  # turn_aborted

def test_stats():
    s = _parse()
    assert s.stats.n_turns == 3
    assert s.stats.n_edits == 4          # a.py x3 + b.py x1
    assert s.stats.n_tool_errors == 1    # b.py patch success=false
    assert s.stats.duration_s == 24.0    # 14:41:20 - 14:40:56

def test_garbage_line_skipped():
    s = _parse()
    assert len(s.turns) == 3   # parsed despite trailing garbage
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_codex_adapter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'totalrecall.adapters.codex'`

- [ ] **Step 4: Implement**

`src/totalrecall/adapters/codex.py`:
```python
from __future__ import annotations
import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from ..models import NormalizedSession, Turn, Event, Stats

EDIT_CHURN_THRESHOLD = 3
_TEXT_TYPES = ("input_text", "output_text")


def _parse_ts(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def _text_from_content(content) -> str:
    if not isinstance(content, list):
        return ""
    return "\n".join(i.get("text", "") for i in content
                     if isinstance(i, dict) and i.get("type") in _TEXT_TYPES)


class CodexAdapter:
    tool = "codex"

    def parse(self, path) -> NormalizedSession:
        session_id = cwd = ""
        started_at = ended_at = None
        turns: list[Turn] = []
        events: list[Event] = []
        file_counts: Counter[str] = Counter()
        n_edits = 0
        n_tool_errors = 0
        idx = 0

        for raw in Path(path).read_text(encoding="utf-8", errors="replace").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                o = json.loads(raw)
            except json.JSONDecodeError:
                continue
            ts = o.get("timestamp")
            if ts:
                started_at = started_at or ts
                ended_at = ts
            typ = o.get("type")
            p = o.get("payload")
            if not isinstance(p, dict):
                continue
            if typ == "session_meta":
                session_id = p.get("id") or session_id
                cwd = p.get("cwd") or cwd
                continue
            ptype = p.get("type")
            if typ == "event_msg":
                if ptype == "turn_aborted":
                    events.append(Event("interrupt", ts, str(p.get("turn_id", "?"))))
                continue
            if typ != "response_item":
                continue
            if ptype == "message":
                role = p.get("role")
                if role in ("user", "assistant"):
                    text = _text_from_content(p.get("content"))
                    if text.strip():
                        turns.append(Turn(idx, role, ts, text=text)); idx += 1
                # role == "developer" (system/dev instructions) -> skip
            elif ptype == "function_call":
                turns.append(Turn(idx, "tool", ts, tool_name=p.get("name"),
                                  tool_status="ok", text=str(p.get("arguments", ""))[:500]))
                idx += 1
            elif ptype == "patch_apply_end":
                changes = p.get("changes")
                if isinstance(changes, dict):
                    for fp in changes.keys():
                        file_counts[fp] += 1
                        n_edits += 1
                if not p.get("success", True):
                    n_tool_errors += 1
                    events.append(Event("tool_error", ts, str(p.get("call_id", "patch"))))
            # function_call_output (unstructured output) / reasoning / others -> skip

        for fp, count in file_counts.items():
            if count >= EDIT_CHURN_THRESHOLD:
                events.append(Event("churn", None, fp))

        start, end = _parse_ts(started_at), _parse_ts(ended_at)
        duration = (end - start).total_seconds() if start and end else 0.0
        return NormalizedSession(
            tool=self.tool, session_id=session_id, cwd=cwd, git_branch=None,
            started_at=started_at, ended_at=ended_at, is_analysis_session=False,
            turns=turns, events=events,
            stats=Stats(n_turns=len(turns), duration_s=duration,
                        n_tool_errors=n_tool_errors, n_edits=n_edits),
        )
```

- [ ] **Step 5: Run tests, then commit**

Run: `python -m pytest tests/test_codex_adapter.py -v`
Expected: PASS
```bash
git add src/totalrecall/adapters/codex.py tests/test_codex_adapter.py tests/fixtures/codex_basic.jsonl
git commit -m "feat: CodexAdapter parses rollout JSONL into NormalizedSession" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: adapters.for_path dispatcher

**Files:**
- Modify: `src/totalrecall/adapters/__init__.py`
- Test: `tests/test_adapters_dispatch.py`

- [ ] **Step 1: Write the failing test**

`tests/test_adapters_dispatch.py`:
```python
from totalrecall import adapters

def test_for_path_routes_codex_vs_cc():
    cdx = adapters.for_path(r"C:\Users\u\.codex\sessions\2026\06\rollout-x.jsonl")
    cc = adapters.for_path(r"C:\Users\u\.claude\projects\proj\s.jsonl")
    assert type(cdx).__name__ == "CodexAdapter"
    assert type(cc).__name__ == "ClaudeCodeAdapter"

def test_for_path_default_is_claude_code():
    assert type(adapters.for_path("/some/other/path.jsonl")).__name__ == "ClaudeCodeAdapter"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_adapters_dispatch.py -v`
Expected: FAIL — `AttributeError: module 'totalrecall.adapters' has no attribute 'for_path'`

- [ ] **Step 3: Implement**

Replace the (empty) `src/totalrecall/adapters/__init__.py` with:
```python
from __future__ import annotations
from .claude_code import ClaudeCodeAdapter
from .codex import CodexAdapter


def for_path(path):
    """Return the adapter for a transcript path, by which source dir it lives under."""
    s = str(path).replace("\\", "/")
    if "/.codex/sessions/" in s:
        return CodexAdapter()
    return ClaudeCodeAdapter()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_adapters_dispatch.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/adapters/__init__.py tests/test_adapters_dispatch.py
git commit -m "feat: adapters.for_path routes by source dir (codex vs claude-code)" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Adapters self-complete; worker dispatches by path

**Files:**
- Modify: `src/totalrecall/adapters/claude_code.py`
- Modify: `src/totalrecall/worker.py`
- Test: `tests/test_worker_codex.py`

**Why:** The Codex adapter computes its own events. The Claude Code adapter currently relies on `worker.process_path` calling `extract_events`. To make the worker tool-agnostic (`for_path(p).parse(p)`), move the event extraction INTO the Claude Code adapter so every adapter returns a *complete* session, then drop the worker's `extract_events` call.

- [ ] **Step 1: Write the failing test**

`tests/test_worker_codex.py`:
```python
from totalrecall import worker, queue, patterns_store, paths, ledger
from totalrecall.adapters.claude_code import ClaudeCodeAdapter
from pathlib import Path

FIX = Path(__file__).parent / "fixtures"

def _fake_analyze(session, catalog, model, runner=None, **kwargs):
    from totalrecall.models import Finding, Evidence
    return [Finding("repeated-correction", "x", 3,
                    Evidence(session.session_id, session.tool, [0], session.ended_at,
                             "h-" + session.session_id), slug="s-" + session.tool)]

def test_cc_adapter_self_computes_events():
    # moving extract_events into the adapter: a parsed CC session already has stats populated
    s = ClaudeCodeAdapter().parse(FIX / "cc_basic.jsonl")
    assert s.stats.n_tool_errors >= 1        # Bash error in cc_basic fixture
    assert s.stats.n_turns == len(s.turns)

def test_worker_processes_codex_via_for_path(home, monkeypatch, tmp_path):
    paths.ensure_dirs()
    # a codex transcript placed under a path containing /.codex/sessions/
    cdir = tmp_path / ".codex" / "sessions" / "2026" / "06"
    cdir.mkdir(parents=True)
    src = (FIX / "codex_basic.jsonl").read_text(encoding="utf-8")
    cf = cdir / "rollout-x.jsonl"; cf.write_text(src, encoding="utf-8")
    queue.enqueue(str(cf))
    monkeypatch.setattr(worker.orchestrator, "analyze", _fake_analyze)
    worker.run_once()
    # the codex session was parsed by CodexAdapter (tool=codex) and merged
    p = patterns_store.get("s-codex")
    assert p is not None and p.evidence[0].tool == "codex"
    assert ledger.Ledger.load().is_new(cf) is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_worker_codex.py -v`
Expected: FAIL — `test_cc_adapter_self_computes_events` fails (CC adapter doesn't populate n_tool_errors yet), and `test_worker_processes_codex_via_for_path` fails (worker still uses the hardcoded CC adapter).

- [ ] **Step 3: Implement**

(a) In `src/totalrecall/adapters/claude_code.py`, add an import after the existing `from ..models import ...` line:
```python
from ..events import extract_events
```
and change the END of `parse` — replace:
```python
        stats = Stats(n_turns=len(turns))
        return NormalizedSession(
            tool=self.tool, session_id=session_id, cwd=cwd, git_branch=git_branch or None,
            started_at=started_at, ended_at=ended_at, is_analysis_session=is_analysis,
            turns=turns, events=[], stats=stats,
        )
```
with:
```python
        session = NormalizedSession(
            tool=self.tool, session_id=session_id, cwd=cwd, git_branch=git_branch or None,
            started_at=started_at, ended_at=ended_at, is_analysis_session=is_analysis,
            turns=turns, events=[], stats=Stats(n_turns=len(turns)),
        )
        extract_events(session)   # populate A-class events + stats (was done by the worker)
        return session
```

(b) In `src/totalrecall/worker.py`, change the import block:
```python
from . import (queue, ledger, config, catalog, merger, render, reconcile,
               orchestrator, paths, synth)
from .adapters.claude_code import ClaudeCodeAdapter
from .events import extract_events
from .locking import try_worker_lock

_ADAPTER = ClaudeCodeAdapter()
```
to:
```python
from . import (queue, ledger, config, catalog, merger, render, reconcile,
               orchestrator, paths, synth, adapters)
from .locking import try_worker_lock
```
and in `process_path`, replace:
```python
    session = _ADAPTER.parse(p)
```
with:
```python
    session = adapters.for_path(p).parse(p)
```
and DELETE the line:
```python
    extract_events(session)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_worker_codex.py tests/test_worker.py tests/test_claude_code_adapter.py tests/test_events.py -v`
Expected: PASS (CC adapter now self-computes events; worker routes by path; existing CC/events tests still green)

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/adapters/claude_code.py src/totalrecall/worker.py tests/test_worker_codex.py
git commit -m "refactor: adapters self-complete (CC computes events); worker dispatches via for_path" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: reconcile scans Codex dir (gated by sources)

**Files:**
- Modify: `src/totalrecall/reconcile.py`
- Test: `tests/test_reconcile_codex.py`

- [ ] **Step 1: Write the failing test**

`tests/test_reconcile_codex.py`:
```python
from totalrecall import reconcile, queue, paths

def test_codex_scanned_when_enabled(home, tmp_path, monkeypatch):
    paths.ensure_dirs()
    paths.config_path().write_text("[sources]\nclaude_code = false\ncodex = true\n", encoding="utf-8")
    cdx = tmp_path / "codex" / "sessions" / "2026" / "06"; cdx.mkdir(parents=True)
    f = cdx / "rollout-x.jsonl"; f.write_text("x", encoding="utf-8")
    monkeypatch.setattr(reconcile, "codex_sessions_dir", lambda: tmp_path / "codex" / "sessions")
    n = reconcile.run(recent_seconds=0)
    assert str(f) in set(queue.drain())
    assert n == 1

def test_codex_not_scanned_when_disabled(home, tmp_path, monkeypatch):
    paths.ensure_dirs()   # default config: codex = false
    cdx = tmp_path / "codex" / "sessions"; cdx.mkdir(parents=True)
    (cdx / "rollout-y.jsonl").write_text("x", encoding="utf-8")
    monkeypatch.setattr(reconcile, "codex_sessions_dir", lambda: cdx)
    monkeypatch.setattr(reconcile, "claude_projects_dir", lambda: tmp_path / "noexist")
    assert reconcile.run(recent_seconds=0) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_reconcile_codex.py -v`
Expected: FAIL — `AttributeError: module 'totalrecall.reconcile' has no attribute 'codex_sessions_dir'`

- [ ] **Step 3: Implement**

In `src/totalrecall/reconcile.py`, add `config` to the imports:
```python
from . import ledger, queue, paths, config
```
Add a Codex dir helper next to `claude_projects_dir`:
```python
def codex_sessions_dir() -> Path:
    return Path.home() / ".codex" / "sessions"
```
Replace the body of `run` with a multi-source scan:
```python
def run(recent_seconds: int = RECENT_SECONDS) -> int:
    """Enqueue settled transcripts newer than the ledger, across enabled sources."""
    cfg = config.load()
    lg = ledger.Ledger.load()
    done = lg.done_paths()
    now = time.time()
    count = 0

    sources = []
    if cfg.sources.get("claude_code"):
        sources.append((claude_projects_dir(), _encoded_analysis_dir()))
    if cfg.sources.get("codex"):
        sources.append((codex_sessions_dir(), None))   # codex sessions are never analysis sessions

    for root, analysis_dir in sources:
        if not root.exists():
            continue
        for jsonl in root.rglob("*.jsonl"):
            if analysis_dir and jsonl.parent.name == analysis_dir:
                continue
            try:
                if now - jsonl.stat().st_mtime < recent_seconds:
                    continue   # in-progress; let it settle
            except OSError:
                continue
            if str(jsonl) in done:
                continue
            if not lg.is_new(jsonl):
                continue
            queue.enqueue(str(jsonl))
            count += 1
    return count
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_reconcile_codex.py tests/test_reconcile.py -v`
Expected: PASS (Codex scanned only when enabled; existing CC reconcile tests still green — default config has `codex = false`)

- [ ] **Step 5: Commit**

```bash
git add src/totalrecall/reconcile.py tests/test_reconcile_codex.py
git commit -m "feat: reconcile scans Codex sessions dir when sources.codex enabled" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: Full suite + README + enablement note

**Files:**
- Modify: `README.md`
- Test: full suite

- [ ] **Step 1: Run the entire suite**

Run: `python -m pytest -q`
Expected: ALL PASS (Phase 1+2's 100 plus the Codex additions)

- [ ] **Step 2: Add a Codex section to README**

Append to `README.md`:
```markdown
## Multi-tool: Codex

Set `codex = true` under `[sources]` in `~/.totalrecall/config.toml` to also learn from
OpenAI Codex CLI sessions (`~/.codex/sessions/.../rollout-*.jsonl`). Codex has no SessionEnd
hook, so its sessions are picked up by `reconcile` — i.e. the next time any `totalrecall worker`
runs (after a Claude Code session ends, or manually). To analyze Codex history immediately,
run `totalrecall reconcile` then `totalrecall worker`. Friction from Codex sessions appears in
`insights.md` with `tool=codex` evidence, in the same pattern library as Claude Code.
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: README Codex multi-tool section" -m "Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 4: Manual enablement + backfill (operational — after merge, when the user wants it)**

This is NOT a code step; it's the operational rollout the user chose (backfill all 98 Codex sessions):
```
# enable codex in ~/.totalrecall/config.toml: under [sources], set codex = true
totalrecall reconcile     # enqueues settled Codex sessions (+ any new CC)
totalrecall worker        # drains them (real claude -p analysis); crash-safe + in-progress-skip apply
totalrecall status        # sessions/patterns climb; insights.md gains tool=codex friction
```
Expected: ~98 Codex sessions analyzed into the same pattern library. (Bounded by the Phase-1
`max_input_tokens` cap and crash-safe queue.)

---

## Self-Review

**Spec coverage (spec §→task):**
- §5 CodexAdapter (session_meta→cwd/session_id/ts; message user/assistant/developer-skip; function_call→tool; patch_apply_end→edit/churn/edit-fail; turn_aborted→interrupt; is_analysis_session=False; stats) → Task 1.
- §6 `adapters.for_path` → Task 2; worker uses it → Task 3.
- §4/§5 "each adapter produces a complete NormalizedSession" (CC event extraction moved into the adapter) → Task 3.
- §7 reconcile scans CC + Codex per `sources` + `codex_sessions_dir()` → Task 4.
- §8 config `sources.codex` (already exists) gates the scan → Task 4.
- §9 trigger = reconcile-based (no hook) → README note Task 5; §2/§11/§13 backfill 98 → Task 5 Step 4 (operational).
- §10 testing → Tasks 1-4 (golden fixture, dispatch, reconcile gating, worker routing).
- §12 risks: #1 changes-dict shape → locked (dict keyed by file path, used in Task 1); #2 no shell error events → Task 1 only counts patch failures; #3 multi-segment content → `_text_from_content` joins all text segments; #4 large sessions → unchanged (Phase-1 cap); #5 backfill operational → Task 5.

**Placeholder scan:** none — all code steps carry complete, runnable code. Task 5 Step 4 is explicitly labeled operational (not a code step).

**Type consistency:** `CodexAdapter.parse(path) -> NormalizedSession` matches the `Adapter` protocol and `ClaudeCodeAdapter.parse`. `NormalizedSession`/`Turn`/`Event`/`Stats` fields used exactly as defined in `models.py` (Phase 1). `adapters.for_path(path)` returns an adapter whose `.parse(p)` the worker calls (Task 3) — consistent. `reconcile.run(recent_seconds=...)` signature unchanged (Task 4 keeps the Phase-1 `recent_seconds` param). `extract_events(session)` (events.py, mutates in place) is now called inside `ClaudeCodeAdapter.parse` (Task 3) and nowhere else — the worker no longer calls it.

**Note on Task 3 ordering:** moving `extract_events` into the CC adapter means a Codex session (which computes its own events) is never double-processed — the worker no longer calls `extract_events` at all, so `CodexAdapter`'s events survive. `test_events.py` still tests `extract_events` directly (unchanged). `test_claude_code_adapter.py` asserts only turns (still pass; the session now also carries events, which is additive).
