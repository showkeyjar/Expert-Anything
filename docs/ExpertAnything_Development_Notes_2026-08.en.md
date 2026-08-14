# ExpertAnything Development Notes (2026-08)

> Iteration history, architecture decisions and engineering conventions from Aug 2026.
> Purpose: fast onboarding for newcomers (including AI collaborators).

## 1. Iteration timeline

| Phase | Content |
|---|---|
| baseline | Flet web prototype + deterministic rule engine (core layer) |
| R1 | PySide6 migration: unified entry (`python app.py`), fixed missing `get_asset()` crash, graph upgrade (layered/radial/anomaly), requirements, README, first git commit |
| R2 | Visualization library: source reader with highlighting (SourceTextView), concept panel (ConceptDetailPanel), path ladder (PathLadderView), live dashboard graph |
| R3 | Structured lesson cards (TeachResultView), history table, Flet UI archived to legacy/ |
| R4 | Understanding-first trio: teach-position mini graph, spaced review queue (`due_for_review`), reference-answer comparison (reference + gap) |
| R5 | Grounded follow-up Q&A (`tutor.follow_up` + FollowUpWorker), review mode (vary=1) |
| R6 | Related-concept navigation (neighbour chips), follow-up questions sink into TeacherModel (`record_learner_question`) |
| R7 | Learning-Gain visuals: stat cards + growth trend chart (TrendChartView) |
| R8 | Crash fix (view-rebuild reference order) + binary import (pdf/epub/docx, ExtractWorker byte pipeline) + file filters |
| R9 | Three-zone layout (top function bar + unified headers), global map (grey_ids + shared-concept edges), single-click panel, progress-bar-free cards, teacher explainer |
| R10 | Map toolbar (search/scope/zoom), teacher-note edges (prerequisite/related, relations 8→37), concept notes as a list |
| R11 | **Living force-directed graph**: physics simulation + floating + drag + hover highlight; slim teach header |
| R12 | Content-fit zoom (≥0.85), bigger node labels, definition tooltips, zoom buttons |
| R13 | Teach-layout fix (graph sizeHint squeezing the lesson area → maxHeight; splitter stretch) |
| R14 | **Multilingual**: zh/en/ja via `t()`, live language switching, 166 hard-coded Chinese literals swept to zero |
| tests | Unified suite `run_tests.py`: 71 cases (core 30 / data 7 / ui 27 / llm 7), quick ~9s |

## 2. Current architecture (stable baseline)

```text
main.py                    PySide6 entry + 7 views + topbar/sidebar
expert_anything/
  core/                    no UI deps
    extraction.py          extraction (LLM chunked-parallel + hallucination guard + noise filter)
    teacher.py             teacher model (ConceptNote + Anomaly + learner-signal loop)
    tutor.py               teaching (3 styles / evaluation reference+gap / follow-up)
    learner.py             cross-asset mastery + adaptive_path + due_for_review
    llm.py                 zero-dep OpenAI-compatible client
    graph_viz.py           layout math + PNG rendering (force initial scatter)
    i18n.py                trilingual key table + t()/set_lang/save_lang
    parsers.py             txt/md/docx/epub/pdf/html extraction
    models.py/storage.py/config.py
  ui/
    pyside_graph.py        living graph (drift/drag/hover/zoom/grey nodes)
    pyside_widgets.py      widget library (panels/cards/sidebar/ladder/trend/distribution)
tests/                     unittest layers (util isolates a demo-data copy)
run_tests.py               one-command entry (--quick / --llm / --layer)
data/_demo                 demo data (two assets + simulated learning, regenerable)
legacy/                    Web + Flet UI + PySide6 v1 archives
```

## 3. Key engineering decisions (ADR supplements)

- **Source grounding**: concepts/evidence verbatim from the source; `_ground_evidence`
  validation; hallucinated concepts dropped; sparse relations get learning-path
  "path-adjacent" edges so the graph always has a skeleton.
- **Teacher-note edges**: prerequisites → "prerequisite" edges, connections matching a
  concept → "related" edges — graph density 8 → 37 relations.
- **Force-directed initial layout = circular scatter**: a layered layout produced a
  4600px-tall strip (unreadable at any zoom); a compact scatter is readable at once and
  the physics spreads it into a natural network.
- **QGraphicsView sizeHint trap**: its sizeHint derives from the scene canvas (can
  exceed 1000px) — inside a QVBoxLayout it must get a `setMaximumHeight`, or it squeezes
  the main content area.
- **View-rebuild lifecycle**: `_rebuild_all_views` clears stale references *before*
  rebuilding; language switching rebuilds topbar + sidebar + all views.
- **i18n module-level evaluation trap**: `TAG_LABELS = {"weak": _t(...)}` freezes the
  language at import — use render-time lookup functions (`_tag_label()`).

## 4. i18n conventions

- All UI text goes through `core/i18n.py` `t(key)`; the key table is trilingual
  (zh-CN/en/ja).
- Learning material (concept names/evidence) is NOT translated; LLM-generated anomaly
  text stays in its generation language.
- The language dropdown shows language self-names (中文/English/日本語).
- New UI copy: add key → translate ×3 → replace the call; verify with a static scan +
  EN-mode dynamic scan for zero leftovers.
- LLM prompt language-following (extraction/teaching output per UI language) is next.

## 5. Known limits & next steps

1. LLM output is fixed Chinese (prompts not language-aware) — next: prompt templates per language
2. No `SourceLocation`: evidence anchors are text-match only, no page/chapter ids
3. `main.py` ~2100-line monolith — split into `ui/views/` pending
4. Scanned PDFs have no OCR; docx covers body paragraphs only
5. JSON-file persistence, not a database yet
6. Learning report is plain text; an HTML visual report is pending

## 6. Testing workflow

```powershell
python run_tests.py --quick   # 71 cases (no LLM), ~9s — run after every change
python run_tests.py           # full (real-LLM end-to-end)
python run_tests.py --layer ui|core|llm|data
```

Discipline: tests use a temp copy of `data/_demo` (tests/util.ensure_demo) and never
touch real data; LLM cases auto-skip without a key.
