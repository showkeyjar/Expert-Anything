"""Domain-specific SceneSpec generators for carbon emission trading.

Second curated domain decoder (after ``decoder_electricity``), built to prove
the domain-decoder layer is registry-driven and reusable — the electricity
module stays untouched, and this module mirrors its contract:

- scenes are hand-curated from the **template** concepts (``ct-*``), whose
  definitions/evidence are themselves textbook-level and time-invariant;
- every spec passes ``check_scene()`` before leaving the generator;
- concept lookup is ID-space agnostic (template ID / asset ID / name+alias)
  via ``domain_templates.resolve_template_concept_id`` — no LLM, no network.
"""
from __future__ import annotations

from expert_anything.core.decoder import check_scene
from expert_anything.core.domain_templates import (
    detect_domain_from_title,
    resolve_template_concept_id,
)


def generate_cap_and_allowance_scene() -> dict | None:
    """总量控制 → 配额 → 分配 → MRV 报告：配额制的基础链条（ct-001/002/003）。"""
    spec = {
        "title": "总量控制与配额分配",
        "nodes": [
            {"id": "n1", "label": "总量控制", "kind": "current"},
            {"id": "n2", "label": "碳排放配额", "kind": "store"},
            {"id": "n3", "label": "免费分配", "kind": "box"},
            {"id": "n4", "label": "有偿拍卖", "kind": "box"},
            {"id": "n5", "label": "排放单位", "kind": "note"},
            {"id": "n6", "label": "MRV 报告", "kind": "flow"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": "设定上限", "type": "causes"},
            {"from": "n2", "to": "n3", "label": "分配方式", "type": "related"},
            {"from": "n2", "to": "n4", "label": "分配方式", "type": "related"},
            {"from": "n3", "to": "n5", "label": "获得配额", "type": "causes"},
            {"from": "n4", "to": "n5", "label": "竞得配额", "type": "causes"},
            {"from": "n5", "to": "n6", "label": "提交", "type": "prereq"},
        ],
        "steps": [
            {"caption": "先定总量：对一定时期内的排放设定上限", "show": ["n1"], "active": "n1"},
            {"caption": "总量切分为配额：排放许可额度", "show": ["n1", "n2"], "active": "n2"},
            {"caption": "两条初始配置路径：免费分配与有偿拍卖", "show": ["n1", "n2", "n3", "n4"], "active": "n3"},
            {"caption": "排放单位持有配额并提交 MRV 报告", "show": ["n1", "n2", "n3", "n4", "n5", "n6"], "active": "n5"},
            {"caption": "配额与 MRV 共同构成合规的前置条件", "show": ["n1", "n2", "n3", "n4", "n5", "n6"], "active": "n6"},
        ],
        "game": {
            "type": "sort",
            "goal": "把配额制的流程按正确顺序排列",
            "items": ["分配配额", "设定总量", "持有履约"],
            "answer": [1, 0, 2],
        },
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


def generate_market_and_price_scene() -> dict | None:
    """交易市场与碳价形成 + CCER 抵消（ct-005/006）。"""
    spec = {
        "title": "碳市场与碳价形成",
        "nodes": [
            {"id": "n1", "label": "碳排放权交易市场", "kind": "current"},
            {"id": "n2", "label": "配额供给", "kind": "store"},
            {"id": "n3", "label": "配额需求", "kind": "store"},
            {"id": "n4", "label": "政策预期", "kind": "note"},
            {"id": "n5", "label": "碳价", "kind": "flow"},
            {"id": "n6", "label": "CCER 抵消", "kind": "box"},
        ],
        "edges": [
            {"from": "n2", "to": "n5", "label": "供给", "type": "causes"},
            {"from": "n3", "to": "n5", "label": "需求", "type": "causes"},
            {"from": "n4", "to": "n5", "label": "预期", "type": "causes"},
            {"from": "n1", "to": "n3", "label": "交易发生", "type": "related"},
            {"from": "n6", "to": "n3", "label": "降低", "type": "causes"},
        ],
        "steps": [
            {"caption": "市场以配额为主要交易标的", "show": ["n1"], "active": "n1"},
            {"caption": "配额供给与需求在市场相遇", "show": ["n1", "n2", "n3"], "active": "n2"},
            {"caption": "政策预期同样进入价格形成", "show": ["n1", "n2", "n3", "n4"], "active": "n4"},
            {"caption": "CCER 抵消能降低配额需求", "show": ["n3", "n6"], "active": "n6"},
            {"caption": "三者共同形成碳价信号", "show": ["n1", "n2", "n3", "n4", "n5", "n6"], "active": "n5"},
        ],
        "game": {
            "type": "sort",
            "goal": "碳价由哪些因素共同形成？（按因果链排序）",
            "items": ["政策预期", "配额供需", "碳价信号"],
            "answer": [1, 0, 2],
        },
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


def generate_compliance_cycle_scene() -> dict | None:
    """履约周期：核算 → 报告 → 核查 → 清缴 + 处罚整改（ct-004/009/010）。"""
    spec = {
        "title": "履约周期与 MRV 流程",
        "nodes": [
            {"id": "n1", "label": "排放核算", "kind": "flow"},
            {"id": "n2", "label": "排放报告", "kind": "flow"},
            {"id": "n3", "label": "第三方核查", "kind": "flow"},
            {"id": "n4", "label": "配额清缴", "kind": "current"},
            {"id": "n5", "label": "履约周期", "kind": "note"},
            {"id": "n6", "label": "处罚/整改", "kind": "box"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": "产出", "type": "causes"},
            {"from": "n2", "to": "n3", "label": "送核", "type": "prereq"},
            {"from": "n3", "to": "n4", "label": "核证后", "type": "causes"},
            {"from": "n5", "to": "n1", "label": "按期启动", "type": "prereq"},
            {"from": "n4", "to": "n6", "label": "未达标触发", "type": "causes"},
        ],
        "steps": [
            {"caption": "履约周期启动：排放单位先核算排放量", "show": ["n5", "n1"], "active": "n1"},
            {"caption": "核算结果形成排放报告", "show": ["n5", "n1", "n2"], "active": "n2"},
            {"caption": "独立第三方核查数据", "show": ["n5", "n1", "n2", "n3"], "active": "n3"},
            {"caption": "以核证数据为准清缴配额，完成履约", "show": ["n5", "n1", "n2", "n3", "n4", "n6"], "active": "n4"},
            {"caption": "未按规定清缴触发处罚与整改", "show": ["n4", "n6"], "active": "n6"},
        ],
        "game": {
            "type": "sort",
            "goal": "把 MRV + 清缴流程按正确顺序排列",
            "items": ["第三方核查", "排放核算", "配额清缴", "排放报告"],
            "answer": [1, 3, 0, 2],
        },
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


def generate_offset_scene() -> dict | None:
    """抵消机制与自愿减排量 + 抵消比例上限（ct-007/008）。"""
    spec = {
        "title": "抵消机制：自愿减排量的用途",
        "nodes": [
            {"id": "n1", "label": "自愿减排项目", "kind": "store"},
            {"id": "n2", "label": "自愿减排量", "kind": "flow"},
            {"id": "n3", "label": "核证", "kind": "box"},
            {"id": "n4", "label": "抵消机制", "kind": "current"},
            {"id": "n5", "label": "履约义务", "kind": "note"},
            {"id": "n6", "label": "抵消比例上限", "kind": "note"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": "产生", "type": "causes"},
            {"from": "n2", "to": "n3", "label": "经", "type": "prereq"},
            {"from": "n3", "to": "n4", "label": "进入", "type": "causes"},
            {"from": "n4", "to": "n5", "label": "抵销部分", "type": "causes"},
            {"from": "n6", "to": "n4", "label": "限制", "type": "prereq"},
        ],
        "steps": [
            {"caption": "自愿减排项目产生减排量", "show": ["n1"], "active": "n1"},
            {"caption": "减排量需经核证才可用", "show": ["n1", "n2", "n3"], "active": "n3"},
            {"caption": "核证减排量通过抵消机制使用", "show": ["n1", "n2", "n3", "n4"], "active": "n4"},
            {"caption": "抵销部分履约义务（有比例上限限制）", "show": ["n1", "n2", "n3", "n4", "n5", "n6"], "active": "n5"},
            {"caption": "超过上限的减排量不能用于当期履约", "show": ["n4", "n6"], "active": "n6"},
        ],
        "game": {
            "type": "sort",
            "goal": "把抵消机制的使用链条按正确顺序排列",
            "items": ["核证", "项目减排", "抵销义务"],
            "answer": [1, 0, 2],
        },
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


DOMAIN_ID = "carbon_trading"

#: Template concept ID (``ct-*``) -> curated scene generator.  Asset concept
#: IDs and concept names are normalized onto these IDs by
#: ``domain_templates.resolve_template_concept_id``.
SCENE_GENERATORS: dict[str, callable] = {
    "ct-001": generate_cap_and_allowance_scene,
    "ct-002": generate_cap_and_allowance_scene,
    "ct-003": generate_cap_and_allowance_scene,
    "ct-005": generate_market_and_price_scene,
    "ct-006": generate_market_and_price_scene,
    "ct-004": generate_compliance_cycle_scene,
    "ct-009": generate_compliance_cycle_scene,
    "ct-010": generate_compliance_cycle_scene,
    "ct-007": generate_offset_scene,
    "ct-008": generate_offset_scene,
}


def scene_for_concept_id(template_concept_id: str) -> dict | None:
    """Curated scene for a template concept ID, or None when there is none."""
    generator = SCENE_GENERATORS.get(str(template_concept_id or "").strip())
    return generator() if generator else None


def get_scene_for_concept(concept_ref: str, asset=None) -> dict | None:
    """Domain scene for a concept, resolved by template ID, asset ID or name.

    Mirrors ``decoder_electricity.get_scene_for_concept``: resolution is
    delegated to ``domain_templates.resolve_template_concept_id`` so the
    scene mapping stays in sync with ``apply_domain_template``.  Returns
    None when the concept has no curated scene.  Deterministic.
    """
    template_id = resolve_template_concept_id(concept_ref, asset, domain_id=DOMAIN_ID)
    if not template_id:
        return None
    return scene_for_concept_id(template_id)


def domain_scene_for(asset, concept, domain: str | None = None) -> dict | None:
    """Domain scene for a concept of ``asset``, gated on the detected domain.

    Same gate as the electricity decoder: the domain comes from ``domain``
    when given, otherwise from ``detect_domain_from_title(asset.title)`` — a
    non-carbon asset never picks up carbon visuals just because a concept
    name collides.  Returns None to mean "no domain scene, use generic".
    """
    if asset is None:
        return None
    if domain is None:
        domain = detect_domain_from_title(getattr(asset, "title", "") or "")
    if domain != DOMAIN_ID:
        return None

    ref = getattr(concept, "id", None) or (
        concept if isinstance(concept, str) else "")
    name = getattr(concept, "name", "") or ""
    template_id = (
        resolve_template_concept_id(ref, asset, domain_id=DOMAIN_ID)
        if ref else ""
    )
    if not template_id and name:
        template_id = resolve_template_concept_id(name, domain_id=DOMAIN_ID)
    if not template_id:
        return None
    return scene_for_concept_id(template_id)
