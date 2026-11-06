"""Domain-specific SceneSpec generators for Distributed Energy Resources (DER).

Fourth curated domain decoder (after ``decoder_electricity``,
``decoder_carbon`` and ``decoder_renewable``), proving the domain-decoder layer
is registry-driven and reusable: the existing modules stay untouched, and this
module mirrors their contract:

- scenes are hand-curated from the **template** concepts (``de-*``), whose
  definitions/evidence are textbook-level and time-invariant engineering
  fundamentals;
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


def generate_resource_form_scene() -> dict | None:
    """资源形态谱系：分布式发电 → 光伏/风电/热电生物质 + 储能/配电（de-001..004）。"""
    spec = {
        "title": "分布式发电资源形态",
        "nodes": [
            {"id": "n1", "label": "分布式发电", "kind": "current"},
            {"id": "n2", "label": "分布式光伏", "kind": "box"},
            {"id": "n3", "label": "分散式风电", "kind": "box"},
            {"id": "n4", "label": "热电/生物质", "kind": "box"},
            {"id": "n5", "label": "储能电池", "kind": "store"},
            {"id": "n6", "label": "配电变压器", "kind": "flow"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": "包含", "type": "part_of"},
            {"from": "n1", "to": "n3", "label": "包含", "type": "part_of"},
            {"from": "n1", "to": "n4", "label": "包含", "type": "part_of"},
            {"from": "n2", "to": "n3", "label": "并列", "type": "contrast"},
            {"from": "n5", "to": "n1", "label": "配套", "type": "prereq"},
            {"from": "n1", "to": "n6", "label": "接入", "type": "causes"},
        ],
        "steps": [
            {"caption": "分布式发电是贴近用户侧的小型发电资源总称", "show": ["n1"], "active": "n1"},
            {"caption": "分布式光伏利用屋顶、车棚等场地就近发电", "show": ["n1", "n2"], "active": "n2"},
            {"caption": "分散式风电单机小、就近接入配电网", "show": ["n1", "n2", "n3"], "active": "n3"},
            {"caption": "热电与生物质利用余热和有机质补充电源", "show": ["n1", "n2", "n3", "n4"], "active": "n4"},
            {"caption": "储能与配电设施是分布式电源友好并网的配套", "show": ["n1", "n5", "n6"], "active": "n5"},
            {"caption": "光伏与风电是并列的新能源形态，共同构成分布式电源", "show": ["n1", "n2", "n3", "n4", "n5", "n6"], "active": "n1"},
        ],
        "game": {
            "type": "sort",
            "goal": "把三种分布式电源按是否依赖天气排序（天气依赖在前）",
            "items": ["热电/生物质", "分布式光伏", "分散式风电"],
            "answer": [2, 1, 0],
        },
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


def generate_aggregation_scene() -> dict | None:
    """聚合形态：微电网 → 虚拟电厂 → 需求响应 + 源网荷储协同/配网调度（de-005/006/007）。"""
    spec = {
        "title": "分布式资源的三种聚合形态",
        "nodes": [
            {"id": "n1", "label": "微电网", "kind": "current"},
            {"id": "n2", "label": "虚拟电厂(VPP)", "kind": "flow"},
            {"id": "n3", "label": "需求响应(DR)", "kind": "store"},
            {"id": "n4", "label": "源网荷储协同", "kind": "box"},
            {"id": "n5", "label": "配网调度", "kind": "note"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": "被聚合", "type": "part_of"},
            {"from": "n3", "to": "n2", "label": "被聚合", "type": "part_of"},
            {"from": "n2", "to": "n3", "label": "协同", "type": "related"},
            {"from": "n4", "to": "n1", "label": "支撑", "type": "prereq"},
            {"from": "n5", "to": "n2", "label": "接入", "type": "causes"},
        ],
        "steps": [
            {"caption": "微电网是本地可控的源-储-荷局部系统", "show": ["n1"], "active": "n1"},
            {"caption": "虚拟电厂把分散资源聚合为可统一调度的整体", "show": ["n1", "n2"], "active": "n2"},
            {"caption": "需求响应引导用户调整用电，等效提供灵活性", "show": ["n1", "n2", "n3"], "active": "n3"},
            {"caption": "VPP 同时聚合发电侧(微电网)与负荷侧(DR)", "show": ["n1", "n2", "n3", "n4"], "active": "n2"},
            {"caption": "源网荷储协同是三种形态的共同基础", "show": ["n1", "n2", "n3", "n4", "n5"], "active": "n4"},
            {"caption": "配网调度统一承接微电网与VPP的出力", "show": ["n1", "n2", "n3", "n4", "n5"], "active": "n5"},
        ],
        "game": {
            "type": "sort",
            "goal": "把三种形态按空间尺度由小到大排序",
            "items": ["虚拟电厂(VPP)", "微电网", "需求响应(DR)"],
            "answer": [1, 0, 2],
        },
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


def generate_balance_scene() -> dict | None:
    """平衡与支撑：削峰填谷 / 就地消纳 / 电压无功 + 储能电池/主网电压（de-008/009/010）。"""
    spec = {
        "title": "分布式资源的平衡与支撑作用",
        "nodes": [
            {"id": "n1", "label": "削峰填谷", "kind": "current"},
            {"id": "n2", "label": "就地消纳", "kind": "box"},
            {"id": "n3", "label": "电压/无功支撑", "kind": "box"},
            {"id": "n4", "label": "储能电池", "kind": "store"},
            {"id": "n5", "label": "主网电压", "kind": "note"},
        ],
        "edges": [
            {"from": "n2", "to": "n1", "label": "减少倒送", "type": "prereq"},
            {"from": "n3", "to": "n1", "label": "支撑并网", "type": "causes"},
            {"from": "n2", "to": "n3", "label": "协同", "type": "related"},
            {"from": "n4", "to": "n1", "label": "物理载体", "type": "prereq"},
            {"from": "n3", "to": "n5", "label": "维持合格", "type": "causes"},
        ],
        "steps": [
            {"caption": "削峰填谷：高峰放电、低谷充电平抑净负荷", "show": ["n1"], "active": "n1"},
            {"caption": "就地消纳在接入点附近直接消耗出力，减少倒送", "show": ["n1", "n2"], "active": "n2"},
            {"caption": "电压/无功支撑维持并网点电压合格", "show": ["n1", "n2", "n3"], "active": "n3"},
            {"caption": "储能是削峰填谷的物理载体", "show": ["n1", "n4"], "active": "n4"},
            {"caption": "电压/无功支撑保障主网电压稳定", "show": ["n3", "n5"], "active": "n5"},
            {"caption": "三者共同保障分布式电源友好并网", "show": ["n1", "n2", "n3", "n4", "n5"], "active": "n1"},
        ],
        "game": {
            "type": "sort",
            "goal": "把三种作用按服务目标排序（并网电压→消纳→曲线）",
            "items": ["削峰填谷", "就地消纳", "电压/无功支撑"],
            "answer": [2, 1, 0],
        },
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


def generate_value_scene() -> dict | None:
    """价值与场景：与电网互动 / 市场化交易 / 韧性 / 碳协同 + 隔墙售电/绿电证书（de-011..014）。"""
    spec = {
        "title": "分布式能源的价值与场景",
        "nodes": [
            {"id": "n1", "label": "与电网互动", "kind": "current"},
            {"id": "n2", "label": "市场化交易", "kind": "flow"},
            {"id": "n3", "label": "韧性提升", "kind": "store"},
            {"id": "n4", "label": "碳减排协同", "kind": "box"},
            {"id": "n5", "label": "隔墙售电", "kind": "note"},
            {"id": "n6", "label": "绿电证书", "kind": "flow"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": "支撑", "type": "causes"},
            {"from": "n1", "to": "n3", "label": "支撑", "type": "causes"},
            {"from": "n2", "to": "n4", "label": "协同", "type": "related"},
            {"from": "n3", "to": "n4", "label": "协同", "type": "related"},
            {"from": "n5", "to": "n2", "label": "渠道", "type": "prereq"},
            {"from": "n6", "to": "n4", "label": "量化", "type": "causes"},
        ],
        "steps": [
            {"caption": "源网荷储协同：分布式资源参与配电网运行", "show": ["n1"], "active": "n1"},
            {"caption": "隔墙售电/绿电交易让分布式发电市场化售电", "show": ["n1", "n2", "n5"], "active": "n2"},
            {"caption": "微电网孤岛运行在主网故障时维持关键负荷", "show": ["n1", "n2", "n3"], "active": "n3"},
            {"caption": "绿电证书量化碳减排贡献", "show": ["n4", "n6"], "active": "n6"},
            {"caption": "就地消纳降低损耗并替代化石电力，协同碳减排", "show": ["n1", "n2", "n3", "n4", "n5", "n6"], "active": "n4"},
            {"caption": "价值闭环：互动→交易→韧性→碳协同", "show": ["n1", "n2", "n3", "n4", "n5", "n6"], "active": "n1"},
        ],
        "game": {
            "type": "sort",
            "goal": "把价值链条按逻辑先后排序",
            "items": ["碳减排协同", "与电网互动", "市场化交易", "韧性提升"],
            "answer": [1, 2, 3, 0],
        },
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


DOMAIN_ID = "distributed_energy"

#: Template concept ID (``de-*``) -> curated scene generator.  Asset concept
#: IDs and concept names are normalized onto these IDs by
#: ``domain_templates.resolve_template_concept_id``.
SCENE_GENERATORS: dict[str, callable] = {
    "de-001": generate_resource_form_scene,
    "de-002": generate_resource_form_scene,
    "de-003": generate_resource_form_scene,
    "de-004": generate_resource_form_scene,
    "de-005": generate_aggregation_scene,
    "de-006": generate_aggregation_scene,
    "de-007": generate_aggregation_scene,
    "de-008": generate_balance_scene,
    "de-009": generate_balance_scene,
    "de-010": generate_balance_scene,
    "de-011": generate_value_scene,
    "de-012": generate_value_scene,
    "de-013": generate_value_scene,
    "de-014": generate_value_scene,
}


def scene_for_concept_id(template_concept_id: str) -> dict | None:
    """Curated scene for a template concept ID, or None when there is none."""
    generator = SCENE_GENERATORS.get(str(template_concept_id or "").strip())
    return generator() if generator else None


def get_scene_for_concept(concept_ref: str, asset=None) -> dict | None:
    """Domain scene for a concept, resolved by template ID, asset ID or name.

    Mirrors ``decoder_electricity.get_scene_for_concept`` /
    ``decoder_carbon.get_scene_for_concept`` / ``decoder_renewable``:
    resolution is delegated to ``domain_templates.resolve_template_concept_id``
    so the scene mapping stays in sync with ``apply_domain_template``.  Returns
    None when the concept has no curated scene.  Deterministic.
    """
    template_id = resolve_template_concept_id(concept_ref, asset, domain_id=DOMAIN_ID)
    if not template_id:
        return None
    return scene_for_concept_id(template_id)


def domain_scene_for(asset, concept, domain: str | None = None) -> dict | None:
    """Domain scene for a concept of ``asset``, gated on the detected domain.

    Same gate as the other decoders: the domain comes from ``domain`` when
    given, otherwise from ``detect_domain_from_title(asset.title)`` — a
    non-DER asset never picks up DER visuals just because a concept name
    collides.  Returns None to mean "no domain scene, use generic".
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
