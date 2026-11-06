"""Semantic-relation measurement against a LOCAL OpenAI-compatible endpoint.

This is the LLM half of the extraction audit; the deterministic half lives in
`verify_extraction_quality.py`. It needs no cloud key -- it talks to a local
llama.cpp / LM Studio / Ollama / vLLM gateway (Vulkan backend on this box).

What it measures (all reproducible, no gold labels needed):
  * semantic relation yield per document and the six-type distribution;
  * how many LLM relations survive the verbatim-evidence gate, and why the
    rest are dropped (attributed per gate rule);
  * evidence locatability / uniqueness / endpoint co-mention of accepted edges;
  * raw `type` legality (before the six-way fold);
  * run-to-run stability (Jaccard) with temperature 0.

It also writes a relation review sheet for a human annotator
(default: docs/semantic_relation_review.md). That sheet is NOT gold data:
it lists candidates and evidence, it does not assert correctness.

Usage:
    set EXPERTANYTHING_LLM_BASE_URL=http://127.0.0.1:8082/v1
    set EXPERTANYTHING_LLM_MODEL=qwen3.5-35b
    set EXPERTANYTHING_LLM_API_KEY=sk-local
    python verify_semantic_extraction.py                 # 3 runs, 2 docs
    python verify_semantic_extraction.py --runs 1 --docs docs/Knowledge_Decoder.md
    python verify_semantic_extraction.py --benchmark     # endpoint + TTFT + tps
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

# Never measure a cached response: stability would be a meaningless 1.0.
os.environ["EXPERTANYTHING_LLM_CACHE"] = "0"

from expert_anything.core import extraction as X                       # noqa: E402
from expert_anything.core.llm import LLMClient, Message, chat_json    # noqa: E402

BASE_URL = os.environ.get("EXPERTANYTHING_LLM_BASE_URL", "http://127.0.0.1:8082/v1")
MODEL = os.environ.get("EXPERTANYTHING_LLM_MODEL", "qwen3.5-35b")
API_KEY = os.environ.get("EXPERTANYTHING_LLM_API_KEY", "sk-local")
REVIEW_PATH = ROOT / "docs" / "semantic_relation_review.md"

DEFAULT_DOCS = [
    "docs/电力交易领域学习方案.md",
    "docs/AutoHarness_Strategy.md",
]

SIX_TYPES = ("prereq", "causes", "part_of", "is_a", "contrast", "related")

# The production extractor calls the endpoint at temperature 0.2. For the
# stability measurement the user asked for 0, so override it here only.
TEMPERATURE = float(os.environ.get("VERIFY_TEMPERATURE", "0"))
MAX_TOKENS = int(os.environ.get("VERIFY_MAX_TOKENS", "8192"))
# llama.cpp's `response_format={"type":"json_object"}` JSON grammar makes this
# local model emit EOS after the first concept (measured: 163 tokens, no
# "relations" key). The production path forces json_mode=True in chat_json();
# the measurement disables it, parses tolerantly, and reports the defect
# separately. Set VERIFY_JSON_MODE=1 to reproduce the production behaviour.
JSON_MODE = os.environ.get("VERIFY_JSON_MODE", "0") == "1"

_orig_call_extract = X._call_extract
_orig_assemble = X._assemble

_JSON_REPAIRS = Counter()


def _repair_stray_quotes(s: str) -> str:
    """Escape unescaped double quotes *inside* JSON string values.

    Small local models emit things like ``"evidence": "知识"解译"成图像…"`` -
    syntactically invalid but clearly the intended string. This only repairs
    quoting; it never rewrites the content, so the text stays auditable
    against the source.
    """
    out: list[str] = []
    in_str = False
    i = 0
    while i < len(s):
        ch = s[i]
        if in_str and ch == "\\" and i + 1 < len(s):
            out.append(s[i:i + 2])
            i += 2
            continue
        if ch == '"':
            if not in_str:
                in_str = True
                out.append(ch)
            else:
                nxt = next((c for c in s[i + 1:] if not c.isspace()), "")
                if nxt in ("", ",", "}", "]", ":"):
                    in_str = False
                    out.append(ch)
                else:
                    out.append('\\"')
            i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def parse_extraction_json(raw: str) -> dict:
    """Tolerant parse: canonical parser first, then quote repair."""
    data = X.parse_llm_json(raw)
    if data.get("concepts"):
        return data
    s = raw.strip()
    s = re.sub(r"^```(?:json)?\s*", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\s*```$", "", s)
    fixed = _repair_stray_quotes(s)
    if fixed != s:
        data = X.parse_llm_json(fixed)
        if data.get("concepts"):
            _JSON_REPAIRS["quote_repair"] += 1
            return data
    return data


def _patched_call_extract(llm, snippet, domain_id=None, concept_skeleton=""):
    system = X.get_domain_prompt("extraction_system", domain_id)
    user = X.get_domain_prompt("extraction_user", domain_id).format(
        chunk_text=snippet, concept_skeleton=concept_skeleton,
    )
    messages = [Message("system", system), Message("user", user)]
    if JSON_MODE:
        return chat_json(
            llm, messages, temperature=TEMPERATURE, max_tokens=MAX_TOKENS,
        )
    last: Exception | None = None
    for _ in range(3):
        try:
            raw = llm.chat(
                messages, temperature=TEMPERATURE,
                json_mode=False, max_tokens=MAX_TOKENS,
            )
        except Exception as exc:  # network / HTTP
            last = exc
            continue
        _JSON_REPAIRS["raw_calls"] += 1
        data = parse_extraction_json(raw)
        if data.get("concepts"):
            return data
        _JSON_REPAIRS["unparseable"] += 1
        last = ValueError("LLM returned empty/non-JSON extraction")
    raise last or ValueError("LLM returned empty/non-JSON extraction")


def _sentence_has_both(text: str, a: str, b: str) -> bool:
    a_low, b_low = a.lower(), b.lower()
    return any(
        a_low in m.group(0).lower() and b_low in m.group(0).lower()
        for m in X._SENTENCE_RE.finditer(text)
    )


def audit_raw_relations(data: dict, asset, text: str) -> dict:
    """Replay _assemble's gate/dedupe rules and attribute every drop."""
    grounded = {c.name.lower(): c.id for c in asset.concepts}
    by_id = {c.id: c.name for c in asset.concepts}
    seen: set[tuple[str, str, str]] = set()
    stats = Counter()
    # (source_lower, target_lower, type) -> how the evidence was obtained
    accepted_kind: dict[tuple[str, str, str], str] = {}
    rejected: list[dict] = []
    for r in data.get("relations", []):
        s = (r.get("source") or "").strip().lower()
        t = (r.get("target") or "").strip().lower()
        raw_ev = (r.get("evidence") or "").strip()
        raw_type = str(r.get("type") or "").strip()
        stats["raw"] += 1
        if raw_type and raw_type not in SIX_TYPES:
            stats["raw_type_off_schema"] += 1
        if not raw_type:
            stats["raw_type_missing"] += 1
        if not s or not t or s not in grounded or t not in grounded:
            stats["drop_endpoint_not_grounded"] += 1
            rejected.append({"rel": r, "form": "endpoint_not_grounded"})
            continue
        if s == t:
            stats["drop_self_loop"] += 1
            rejected.append({"rel": r, "form": "self_loop"})
            continue
        s_name, t_name = by_id[grounded[s]], by_id[grounded[t]]
        if raw_ev and raw_ev in text:
            stats["evidence_verbatim"] += 1
            ev = raw_ev
            kind = "verbatim"
        else:
            stats["evidence_not_verbatim"] += 1
            ev = X._recover_relation_evidence(text, s_name, t_name, raw_ev)
            if ev:
                stats["evidence_recovered"] += 1
                kind = "recovered_sentence"
            else:
                stats["drop_no_support"] += 1
                if raw_ev and _sentence_has_both(text, s_name, t_name):
                    form = "gate_internal_error"  # sentence exists but gate said no
                elif not raw_ev:
                    form = "empty_evidence"
                elif not _sentence_has_both(text, s_name, t_name):
                    form = "no_span_names_both"  # alias / pronoun / cross-paragraph
                else:
                    form = "unknown"
                stats["form_" + form] += 1
                rejected.append({"rel": r, "form": form})
                continue
        # Accepted edges whose evidence is verbatim but names neither endpoint
        # are the weak spot: the span is real, the claim is not stated there.
        ev_low = ev.lower()
        named = int(s_name.lower() in ev_low) + int(t_name.lower() in ev_low)
        stats[f"accepted_evidence_names_{named_of_two(named)}"] += 1
        rtype = X._canonical_relation_type(
            (r.get("label") or "").strip(), raw_type
        )
        if rtype not in SIX_TYPES:
            stats["drop_invalid_type"] += 1
            rejected.append({"rel": r, "form": "invalid_type"})
            continue
        if rtype != raw_type:
            stats["type_folded"] += 1
        key = ((min(grounded[s], grounded[t]), max(grounded[s], grounded[t]), rtype)
               if rtype == "contrast" else (grounded[s], grounded[t], rtype))
        if key in seen:
            stats["drop_duplicate"] += 1
            rejected.append({"rel": r, "form": "duplicate"})
            continue
        seen.add(key)
        stats["accepted"] += 1
        if kind == "recovered_sentence":
            stats["accepted_recovered"] += 1
        if len(ev) != len(text) and text.count(ev) != 1:
            stats["accepted_non_unique_anchor"] += 1
        accepted_kind[(s_name.lower(), t_name.lower(), rtype)] = kind
    stats["accepted_asset"] = len(asset.relations)
    return {"stats": stats, "rejected": rejected, "kind": accepted_kind}


def named_of_two(named: int) -> str:
    return {2: "both", 1: "one", 0: "none"}[named]


def run_once(text: str, filename: str, llm: LLMClient) -> dict:
    captured: dict = {}

    def wrapper(data, text_, filename_, method, page_offsets=None):
        asset = _orig_assemble(data, text_, filename_, method, page_offsets)
        captured["audit"] = audit_raw_relations(data, asset, text_)
        captured["raw"] = data
        captured["asset"] = asset
        return asset

    X._call_extract = _patched_call_extract
    X._assemble = wrapper
    try:
        asset = X.extract_knowledge(text, filename, llm=llm)
    finally:
        X._call_extract = _orig_call_extract
        X._assemble = _orig_assemble
    if "asset" not in captured:
        raise RuntimeError(
            f"{filename}: LLM path did not reach _assemble (method={asset.method})"
        )
    return captured


def jaccard(a: set, b: set) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def relation_set(asset) -> set:
    by_id = {c.id: c.name.lower() for c in asset.concepts}
    return {(by_id[r.source], by_id[r.target], r.type) for r in asset.relations}


def hard_tag(rel, kind: str, source_name: str, target_name: str) -> str:
    ev = rel.evidence or ""
    tags = []
    if kind == "recovered_sentence":
        tags.append("同句恢复(别名/指代)")
    if "\n" in ev:
        tags.append("跨行/跨段")
    if re.match(r"^\s*(?:[-*•]|\d+[.、)])\s", ev):
        tags.append("列表项")
    if len(ev) > 200:
        tags.append("长跨度")
    low = ev.lower()
    named = int(source_name.lower() in low) + int(target_name.lower() in low)
    if named == 0:
        tags.append("证据未点名两端")
    elif named == 1:
        tags.append("证据只点名一端")
    if rel.type in ("contrast", "related"):
        tags.append("对比/弱关联")
    return "、".join(tags) or "普通"


def _line_of(text: str, pos: int) -> int:
    return text.count("\n", 0, pos) + 1 if pos >= 0 else 0


def build_review_items(asset, audit: dict, text: str, limit: int = 20) -> list[dict]:
    """15-20 candidates for a human: hard accepted edges first, then rejects."""
    by_id = {c.id: c.name for c in asset.concepts}
    rows: list[dict] = []
    for r in asset.relations:
        s_name = by_id.get(r.source, r.source)
        t_name = by_id.get(r.target, r.target)
        kind = audit["kind"].get((s_name.lower(), t_name.lower(), r.type), "verbatim")
        tag = hard_tag(r, kind, s_name, t_name)
        loc = r.location
        rows.append({
            "status": "accepted",
            "source": s_name, "target": t_name, "type": r.type, "label": r.label,
            "evidence": r.evidence,
            "line": loc.line if loc else 0,
            "char": loc.char_start if loc else -1,
            "hard": tag,
            "priority": 0 if "证据未点名两端" in tag or "同句恢复" in tag else 1,
        })
    for item in audit["rejected"]:
        if item["form"] not in ("no_span_names_both", "empty_evidence",
                                "endpoint_not_grounded"):
            continue
        raw = item["rel"]
        ev = str(raw.get("evidence") or "").strip()
        pos = text.find(ev) if ev else -1
        reason = {
            "no_span_names_both": "被拒：原文无同句同时点名两端（别名/指代/跨段）",
            "empty_evidence": "被拒：未给证据",
            "endpoint_not_grounded": "被拒：端点概念未通过逐字锚定",
        }[item["form"]]
        rows.append({
            "status": reason,
            "source": str(raw.get("source") or ""),
            "target": str(raw.get("target") or ""),
            "type": str(raw.get("type") or ""),
            "label": str(raw.get("label") or ""),
            "evidence": ev,
            "line": _line_of(text, pos),
            "char": pos,
            "hard": "难例(被闸门拒绝)",
            "priority": 0,
        })
    rows.sort(key=lambda x: x["priority"])
    return rows[:limit]


def write_review(per_doc: list[dict], path: Path) -> None:
    lines = [
        "# 语义关系待人工复核清单",
        "",
        "> 由 `verify_semantic_extraction.py` 自动生成。**这不是金标**：只列出现象，",
        "> 不判断对错。请在「你的判断」列填 ✅正确 / ✖错误 / ?拿不准，并可补充说明。",
        "> 每条都给出证据原文与字符偏移，可直接跳原文核对。",
        "",
    ]
    for doc in per_doc:
        lines += [
            f"## {doc['path']}", "",
            f"- 模型：`{doc['model']}`，温度 {doc['temperature']}，运行 {doc['runs']} 次",
            f"- 接受语义边：{doc['accepted']} 条；六类分布：{doc['types']}",
            f"- 证据形态：逐字 {doc['verbatim']} / 同句恢复 {doc['recovered']} / "
            f"拒绝 {doc['no_support']}",
            "",
            "| # | 状态 | source → target | type | label | 证据（前 120 字） | 位置(行/字符) | 难例类型 | 你的判断 |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for i, item in enumerate(doc["items"], 1):
            ev = (item["evidence"] or "").replace("\n", "⏎").replace("|", "\\|")
            src = item["source"].replace("|", "\\|")
            tgt = item["target"].replace("|", "\\|")
            lines.append(
                f"| {i} | {item['status']} | {src} → {tgt} | {item['type']} | "
                f"{item['label']} | {ev[:120]} | L{item['line']} @{item['char']} | "
                f"{item['hard']} |  |"
            )
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _post_json(payload: dict, timeout: int = 180) -> dict:
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {API_KEY}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def benchmark() -> None:
    """Endpoint metadata + prefill/decode throughput + stream TTFT."""
    print("endpoint:", BASE_URL)
    with urllib.request.urlopen(f"{BASE_URL}/models", timeout=30) as resp:
        models = json.loads(resp.read().decode())
    print("models:", [m.get("id") for m in models.get("data", [])])
    root = BASE_URL[:-3] if BASE_URL.endswith("/v1") else BASE_URL
    try:
        with urllib.request.urlopen(f"{root}/props", timeout=30) as resp:
            props = json.loads(resp.read().decode())
        print("props:", json.dumps({
            "alias": props.get("model_alias"),
            "ftype": props.get("model_ftype"),
            "n_ctx": (props.get("default_generation_settings") or {}).get("n_ctx"),
            "slots": props.get("total_slots"),
            "build": props.get("build_info"),
        }, ensure_ascii=False))
    except Exception as exc:  # not a llama.cpp server
        print("props: unavailable", exc)

    prompt = "用一句话解释什么是节点边际电价。"
    data = _post_json({"model": MODEL,
                       "messages": [{"role": "user", "content": prompt}],
                       "temperature": 0, "max_tokens": 64})
    t = data.get("timings") or {}
    content = data["choices"][0]["message"]["content"]
    print("non-stream: prompt_n=%s prompt_tps=%.1f gen_n=%s gen_tps=%.1f wall=%.2fs chars=%d"
          % (t.get("prompt_n"), (t.get("prompt_per_second") or 0),
             t.get("predicted_n"), (t.get("predicted_per_second") or 0),
             (t.get("prompt_ms", 0) + t.get("predicted_ms", 0)) / 1000,
             len(content)))

    payload = {"model": MODEL,
               "messages": [{"role": "user", "content": prompt}],
               "temperature": 0, "max_tokens": 64, "stream": True}
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE_URL}/chat/completions", data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {API_KEY}"},
        method="POST",
    )
    start = time.time()
    ttft = None
    text = ""
    n_chunks = 0
    with urllib.request.urlopen(req, timeout=180) as resp:
        for raw in resp:
            line = raw.decode("utf-8", "ignore").strip()
            if not line.startswith("data:"):
                continue
            chunk = line[5:].strip()
            if chunk == "[DONE]":
                break
            try:
                obj = json.loads(chunk)
            except json.JSONDecodeError:
                continue
            piece = obj["choices"][0].get("delta", {}).get("content") or ""
            if piece:
                n_chunks += 1
                if ttft is None:
                    ttft = time.time() - start
                text += piece
    total = time.time() - start
    print("stream: ttft=%.2fs wall=%.2fs chunks=%d decode_tps=%.1f"
          % (ttft or -1, total, n_chunks,
             len(text) / max(total - (ttft or 0), 1e-6)))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", nargs="+", default=DEFAULT_DOCS)
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--benchmark", action="store_true")
    args = ap.parse_args()

    if args.benchmark:
        benchmark()
        return

    llm = LLMClient(API_KEY, BASE_URL, MODEL, timeout=600, max_concurrency=1)
    per_doc = []
    for doc in args.docs:
        text = (ROOT / doc).read_text(encoding="utf-8", errors="replace")
        assets, audits, sets, concepts = [], [], [], []
        t0 = time.time()
        for i in range(args.runs):
            started = time.time()
            out = run_once(text, Path(doc).name, llm)
            asset, audit = out["asset"], out["audit"]
            assets.append(asset)
            audits.append(audit)
            sets.append(relation_set(asset))
            concepts.append({c.name.lower() for c in asset.concepts})
            print(f"  {doc} run {i + 1}/{args.runs}: concepts={len(asset.concepts)} "
                  f"relations={len(asset.relations)} accepted_raw={audit['stats']['accepted']} "
                  f"raw={audit['stats']['raw']} "
                  f"({time.time() - started:.1f}s, method={asset.method})", flush=True)
        first = assets[0]
        types = Counter(r.type for r in first.relations)
        items = build_review_items(first, audits[0], text, limit=20)
        s0 = audits[0]["stats"]
        per_doc.append({
            "path": doc,
            "runs": args.runs,
            "model": MODEL,
            "temperature": TEMPERATURE,
            "stats": audits,
            "sets": sets,
            "concepts": concepts,
            "elapsed": time.time() - t0,
            "types": dict(types),
            "accepted": len(first.relations),
            "verbatim": s0["evidence_verbatim"],
            "recovered": s0["evidence_recovered"],
            "no_support": s0["drop_no_support"],
            "items": items,
        })

    print("\n=== SUMMARY ===")
    for d in per_doc:
        s = d["stats"][0]["stats"]
        jac = [jaccard(d["sets"][i], d["sets"][i + 1])
               for i in range(len(d["sets"]) - 1)]
        cjac = [jaccard(d["concepts"][i], d["concepts"][i + 1])
                for i in range(len(d["concepts"]) - 1)]
        print(f"\n{d['path']}  ({d['elapsed']:.1f}s total, {d['runs']} runs)")
        print(f"  concepts={len(d['concepts'][0])} "
              f"semantic_edges={s['accepted_asset']} ")
        print(f"  raw_relations={s['raw']} accepted_by_gate={s['accepted']} "
              f"(diff={s['raw'] - s['accepted']})")
        print(f"  types(asset run1)={d['types']}")
        print(f"  evidence: verbatim={s['evidence_verbatim']} "
              f"recovered={s['evidence_recovered']} "
              f"not_verbatim={s['evidence_not_verbatim']}")
        gate_in = s["evidence_verbatim"] + s["evidence_recovered"]
        print(f"  evidence_pass_rate={gate_in}/{s['raw']}"
              f"={gate_in / max(s['raw'], 1):.1%}")
        print(f"  accepted obvious: both={s['accepted_evidence_names_both']} "
              f"one={s['accepted_evidence_names_one']} "
              f"none={s['accepted_evidence_names_none']}")
        print(f"  non_unique_anchor_accepted={s['accepted_non_unique_anchor']}")
        print(f"  raw_type: off_schema={s['raw_type_off_schema']} "
              f"missing={s['raw_type_missing']} folded={s['type_folded']} "
              f"invalid_after_fold={s['drop_invalid_type']}")
        print(f"  drops: endpoint_not_grounded={s['drop_endpoint_not_grounded']} "
              f"no_support={s['drop_no_support']} "
              f"duplicate={s['drop_duplicate']} self_loop={s['drop_self_loop']}")
        for k, v in sorted(s.items()):
            if k.startswith("form_"):
                print(f"    reject_form {k}={v}")
        print(f"  jaccard_edges={[round(x, 2) for x in jac]} "
              f"jaccard_concepts={[round(x, 2) for x in cjac]}")
        print(f"  review_items={len(d['items'])}")

    write_review(per_doc, REVIEW_PATH)
    print(f"\nreview sheet -> {REVIEW_PATH}")


if __name__ == "__main__":
    main()
