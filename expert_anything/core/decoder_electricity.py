"""Domain-specific SceneSpec generators for electricity trading.

Provides pre-built visualizations for key electricity market concepts,
complementing the general-purpose decoder. Each generator produces a
SceneSpec that passes check_scene() and renders to interactive HTML.

Concept lookup is ID-space agnostic: ``get_scene_for_concept`` accepts a
template concept ID (``et-001``), an asset concept ID (``c001``) or a concept
name/alias, and normalizes all of them onto the template IDs through
``domain_templates.resolve_template_concept_id`` — no LLM, no network.
"""
from __future__ import annotations

from expert_anything.core.decoder import check_scene, render_interactive_html
from expert_anything.core.domain_templates import (
    detect_domain_from_title,
    resolve_template_concept_id,
)


def generate_market_architecture_scene() -> dict:
    """Generate visualization for the two-level market architecture."""
    spec = {
        "title": "中国电力市场两级架构",
        "nodes": [
            {"id": "n1", "label": "中国电力交易中心", "kind": "current"},
            {"id": "n2", "label": "区域交易中心", "kind": "box"},
            {"id": "n3", "label": "省级交易中心", "kind": "box"},
            {"id": "n4", "label": "电力用户", "kind": "store"},
            {"id": "n5", "label": "发电企业", "kind": "store"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": "协调"},
            {"from": "n1", "to": "n3", "label": "监管"},
            {"from": "n2", "to": "n4", "label": "跨省交易"},
            {"from": "n3", "to": "n4", "label": "省内交易"},
            {"from": "n5", "to": "n3", "label": "上网电量"},
        ],
        "steps": [
            {"caption": "顶层：中国电力交易中心负责全国设计", "show": ["n1"], "active": "n1"},
            {"caption": "中层：区域+省级交易中心分工运作", "show": ["n1", "n2", "n3"], "active": "n2"},
            {"caption": "底层：发电企业与电力用户通过市场交易", "show": ["n1", "n2", "n3", "n4", "n5"], "active": "n5"},
        ],
        "game": None
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


def generate_price_formation_scene() -> dict:
    """Generate visualization for price formation mechanism."""
    spec = {
        "title": "电价形成机制",
        "nodes": [
            {"id": "n1", "label": "上网电价", "kind": "store"},
            {"id": "n2", "label": "输配电价", "kind": "store"},
            {"id": "n3", "label": "政府基金", "kind": "note"},
            {"id": "n4", "label": "销售电价", "kind": "current"},
            {"id": "n5", "label": "现货价格", "kind": "flow"},
        ],
        "edges": [
            {"from": "n1", "to": "n4", "label": "+"},
            {"from": "n2", "to": "n4", "label": "+"},
            {"from": "n3", "to": "n4", "label": "+"},
            {"from": "n5", "to": "n4", "label": "替代"},
        ],
        "steps": [
            {"caption": "传统电价 = 上网电价 + 输配电价 + 政府基金", "show": ["n1", "n2", "n3", "n4"], "active": "n4"},
            {"caption": "现货市场下，上网电价由实时供需决定", "show": ["n1", "n2", "n3", "n4", "n5"], "active": "n5"},
        ],
        "game": {
            "type": "sort",
            "goal": "把电价构成要素按正确顺序排列",
            "items": ["上网电价", "输配电价", "政府基金", "销售电价"],
            "answer": [0, 1, 2, 3]
        }
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


def generate_trading_process_scene() -> dict:
    """Generate visualization for day-ahead market process."""
    spec = {
        "title": "日前市场交易流程",
        "nodes": [
            {"id": "n1", "label": "发电报价", "kind": "flow"},
            {"id": "n2", "label": "负荷预测", "kind": "flow"},
            {"id": "n3", "label": "出清计算", "kind": "flow"},
            {"id": "n4", "label": "发布结果", "kind": "flow"},
            {"id": "n5", "label": "履约执行", "kind": "flow"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": "并发"},
            {"from": "n1", "to": "n3", "label": "输入"},
            {"from": "n2", "to": "n3", "label": "输入"},
            {"from": "n3", "to": "n4", "label": "输出"},
            {"from": "n4", "to": "n5", "label": "执行"},
        ],
        "steps": [
            {"caption": "日前市场：发电企业提交次日报价", "show": ["n1"], "active": "n1"},
            {"caption": "同时进行负荷预测", "show": ["n1", "n2"], "active": "n2"},
            {"caption": "调度机构进行出清计算", "show": ["n1", "n2", "n3"], "active": "n3"},
            {"caption": "发布次日发电计划", "show": ["n1", "n2", "n3", "n4"], "active": "n4"},
            {"caption": "按中标结果履约执行", "show": ["n1", "n2", "n3", "n4", "n5"], "active": "n5"},
        ],
        "game": {
            "type": "sort",
            "goal": "把日前市场流程按正确顺序排列",
            "items": ["出清计算", "发电报价", "履约执行", "负荷预测", "发布结果"],
            "answer": [1, 3, 0, 4, 2]
        }
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


def generate_lmp_scene() -> dict:
    """Generate visualization for Locational Marginal Price (LMP)."""
    spec = {
        "title": "节点边际电价(LMP)构成",
        "nodes": [
            {"id": "n1", "label": "电能价值", "kind": "box"},
            {"id": "n2", "label": "阻塞成本", "kind": "box"},
            {"id": "n3", "label": "网损成本", "kind": "box"},
            {"id": "n4", "label": "节点边际电价", "kind": "current"},
        ],
        "edges": [
            {"from": "n1", "to": "n4", "label": "+"},
            {"from": "n2", "to": "n4", "label": "+"},
            {"from": "n3", "to": "n4", "label": "+"},
        ],
        "steps": [
            {"caption": "LMP的第一部分：电能价值（能量节点的价格）", "show": ["n1", "n4"], "active": "n1"},
            {"caption": "LMP的第二部分：阻塞成本（输电约束导致）", "show": ["n1", "n2", "n4"], "active": "n2"},
            {"caption": "LMP的第三部分：网损成本（传输损耗）", "show": ["n1", "n2", "n3", "n4"], "active": "n3"},
            {"caption": "LMP = 电能价值 + 阻塞成本 + 网损成本", "show": ["n1", "n2", "n3", "n4"], "active": "n4"},
        ],
        "game": {
            "type": "sort",
            "goal": "把LMP的三个组成部分按重要性排序",
            "items": ["阻塞成本", "电能价值", "网损成本"],
            "answer": [1, 0, 2]
        }
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


DOMAIN_ID = "electricity_trading"

#: Template concept ID -> curated scene generator.  Keys are the *template*
#: (``et-*``) IDs, which is the single stable key space; references coming
#: from an asset (``c001``) or a lesson (a concept name) are normalized onto
#: these IDs by ``domain_templates.resolve_template_concept_id``.
SCENE_GENERATORS: dict[str, callable] = {
    "et-001": generate_market_architecture_scene,
    "et-010": generate_price_formation_scene,
    "et-011": generate_price_formation_scene,
    "et-012": generate_price_formation_scene,
    "et-013": generate_lmp_scene,
    "et-015": generate_trading_process_scene,
}


def scene_for_concept_id(template_concept_id: str) -> dict | None:
    """Curated scene for a template concept ID, or None when there is none."""
    generator = SCENE_GENERATORS.get(str(template_concept_id or "").strip())
    return generator() if generator else None


def get_scene_for_concept(concept_ref: str, asset=None) -> dict | None:
    """Domain scene for a concept, resolved by template ID, asset ID or name.

    ``concept_ref`` may be a template concept ID (``et-001``), an asset
    concept ID (``c001`` — resolved through the asset concept's name) or any
    spelling of a concept name (``节点边际电价`` / ``节点边际电价(LMP)`` /
    ``LMP``).  Pass ``asset`` to enable the asset-ID route.

    Resolution is delegated to ``domain_templates.resolve_template_concept_id``
    so it stays in sync with the template mapping used by
    ``apply_domain_template``.  Returns None when the concept has no curated
    scene, so callers can fall back to the generic decoder.  Deterministic:
    no LLM, no network.
    """
    template_id = resolve_template_concept_id(concept_ref, asset)
    if not template_id:
        return None
    return scene_for_concept_id(template_id)


def domain_scene_for(asset, concept, domain: str | None = None) -> dict | None:
    """Domain scene for a concept of ``asset``, gated on the detected domain.

    ``concept`` may be a concept object (``.id`` / ``.name``) or a raw
    reference string.  The domain comes from ``domain`` when given, otherwise
    from ``detect_domain_from_title(asset.title)`` — so a non-electricity
    asset never picks up electricity visuals just because a concept name
    happens to collide.  Returns None to mean "no domain scene here, use the
    generic decoder".
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
    template_id = resolve_template_concept_id(ref, asset) if ref else ""
    if not template_id and name:
        # The asset's own spelling may differ from the template's.
        template_id = resolve_template_concept_id(name)
    if not template_id:
        return None
    return scene_for_concept_id(template_id)
