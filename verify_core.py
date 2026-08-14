"""Headless verification of the core learning loop (no GUI, no LLM key)."""

import sys
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    sys.stderr.reconfigure(encoding='utf-8', errors='replace')
import sys, tempfile, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Force a temp data dir so we don't touch the user's real data.
tmp = tempfile.mkdtemp()
os.environ["EXPERTANYTHING_DATA_DIR"] = tmp

from expert_anything.core import config
from expert_anything.core.extraction import extract_knowledge
from expert_anything.core.tutor import Tutor
from expert_anything.core import learner, storage

SAMPLE = """
# 设计 Agent Memory

## 为什么需要 Memory
Agent 在执行多轮任务时会丢失上下文，Memory 让 Agent 跨回合保留关键信息。

## Memory 的类型
有短期记忆（当前会话）和长期记忆（写入外部存储如向量库）。

## 与 Context Engineering 的关系
Memory 是 Context Engineering 的一部分，负责在合适时机把信息塞回上下文。

## 实践建议
先定义要记什么，再选择存储介质，最后做召回与压缩。
"""

print("[1] extracting (fallback, no LLM key)...")
asset = extract_knowledge(SAMPLE, "agent-memory.md", llm=None)
assert asset.concepts, "no concepts extracted"
print(f"    title={asset.title!r} concepts={len(asset.concepts)} relations={len(asset.relations)} path={len(asset.learning_path)} method={asset.method}")
assert asset.method == "deterministic_fallback_v1"

print("[2] persisting + reloading...")
storage.save_asset(asset)
reloaded = storage.load_assets()
assert reloaded and reloaded[0].asset_id == asset.asset_id
print(f"    reloaded {len(reloaded)} asset(s)")

print("[3] learner registration + alignment...")
state = learner.load()
learner.register_asset(state, asset)
learner.set_profile(state, "能设计一个可用的 Agent Memory", "了解一些", "例子")
learner.save(state)

print("[4] tutor teach (fallback)...")
tutor = Tutor(asset, llm=None)
first_id = asset.learning_path[0]
c = asset.concept_by_id(first_id)
lesson = tutor.teach(c)
print(f"    concept={c.name!r} explanation_len={len(lesson['explanation'])} practice={lesson['practice'][:30]!r}")

print("[5] tutor evaluate (fallback) + record...")
result = tutor.evaluate(c, "Memory 让 Agent 跨回合保留信息，是 Context Engineering 的一部分。")
print(f"    score={result['score']} understood={result['understood']}")
new_m = learner.record_evaluation(state, c.name, asset.asset_id, result["score"], "ans", result["feedback"])
learner.mark_completed(state, asset.asset_id, c.id)
learner.save(state)
print(f"    updated mastery={new_m}")

print("[6] weaknesses + next concept...")
state2 = learner.load()
print(f"    weaknesses={[w['name'] for w in learner.weaknesses(state2)]}")
nxt = learner.next_concept_id(state2, asset)
print(f"    next_concept_id={nxt}")

print("\nALL CORE CHECKS PASSED")
