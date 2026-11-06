"""Domain-specific SceneSpec generators for renewable energy power forecasting.

Third curated domain decoder (after ``decoder_electricity`` and
``decoder_carbon``), built to prove the domain-decoder layer is registry-driven
and reusable: the existing modules stay untouched, and this module mirrors
their contract:

- scenes are hand-curated from the **template** concepts (``rf-*``), whose
  definitions/evidence are themselves textbook-level and time-invariant
  engineering fundamentals;
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


def generate_forecast_horizons_scene() -> dict | None:
    """预测尺度时间轴 + 日前市场：超短期 → 短期 → 中长期（rf-001/002/003/004）。"""
    spec = {
        "title": "新能源预测尺度时间轴",
        "nodes": [
            {"id": "n1", "label": "超短期预测", "kind": "current"},
            {"id": "n2", "label": "短期（日前）预测", "kind": "box"},
            {"id": "n3", "label": "中长期预测", "kind": "box"},
            {"id": "n4", "label": "实时调度", "kind": "store"},
            {"id": "n5", "label": "市场交易/电量平衡", "kind": "store"},
            {"id": "n6", "label": "日前市场", "kind": "flow"},
        ],
        "edges": [
            {"from": "n1", "to": "n4", "label": "支撑", "type": "prereq"},
            {"from": "n2", "to": "n5", "label": "支撑", "type": "prereq"},
            {"from": "n3", "to": "n5", "label": "支撑", "type": "prereq"},
            {"from": "n1", "to": "n2", "label": "滚动衔接", "type": "prereq"},
            {"from": "n2", "to": "n3", "label": "递进", "type": "prereq"},
            {"from": "n2", "to": "n6", "label": "核心依据", "type": "causes"},
        ],
        "steps": [
            {"caption": "超短期：数分钟至4小时，滚动更新，服务实时调度", "show": ["n1", "n4"], "active": "n1"},
            {"caption": "短期/日前：0-72小时，是市场交易与日前市场的主要依据", "show": ["n1", "n2", "n5", "n6"], "active": "n2"},
            {"caption": "中长期：数日至数月，服务检修计划与电量平衡", "show": ["n1", "n2", "n3", "n5"], "active": "n3"},
            {"caption": "日前市场以日前预测为核心输入", "show": ["n2", "n6"], "active": "n6"},
            {"caption": "记住：尺度越短越服务实时调度，越长越服务规划与平衡", "show": ["n1", "n2", "n3", "n4", "n5", "n6"], "active": "n1"},
        ],
        "game": {
            "type": "sort",
            "goal": "把三类预测尺度按时间由短到长排序",
            "items": ["中长期预测", "超短期预测", "短期（日前）预测"],
            "answer": [1, 2, 0],
        },
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


def generate_nwp_driver_scene() -> dict | None:
    """NWP 驱动链 + 集合预报：NWP/气象要素 → 功率曲线 → 出力预测（rf-005/006/008）。"""
    spec = {
        "title": "NWP 驱动的功率预测链路",
        "nodes": [
            {"id": "n1", "label": "数值天气预报(NWP)", "kind": "current"},
            {"id": "n2", "label": "气象要素", "kind": "note"},
            {"id": "n3", "label": "功率曲线", "kind": "box"},
            {"id": "n4", "label": "历史出力数据", "kind": "store"},
            {"id": "n5", "label": "出力预测", "kind": "flow"},
            {"id": "n6", "label": "集合预报", "kind": "box"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": "产出", "type": "causes"},
            {"from": "n2", "to": "n3", "label": "驱动", "type": "causes"},
            {"from": "n3", "to": "n5", "label": "映射", "type": "causes"},
            {"from": "n4", "to": "n5", "label": "训练/校验", "type": "prereq"},
            {"from": "n1", "to": "n6", "label": "多成员", "type": "causes"},
        ],
        "steps": [
            {"caption": "NWP 对未来风速、辐照、温度做网格化预报", "show": ["n1", "n6"], "active": "n1"},
            {"caption": "气象要素作为物理建模的输入", "show": ["n1", "n2"], "active": "n2"},
            {"caption": "功率曲线把风速/辐照映射为出力", "show": ["n1", "n2", "n3"], "active": "n3"},
            {"caption": "集合预报多成员刻画不确定性", "show": ["n1", "n6"], "active": "n6"},
            {"caption": "结合历史数据训练/校验，得到出力预测", "show": ["n1", "n2", "n3", "n4", "n5", "n6"], "active": "n5"},
        ],
        "game": {
            "type": "sort",
            "goal": "把功率预测的驱动链路按先后顺序排列",
            "items": ["功率曲线映射", "NWP预报", "出力预测", "历史数据校验"],
            "answer": [1, 0, 3, 2],
        },
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


def generate_power_curve_scene() -> dict | None:
    """功率曲线 + 损失系数：风速 → 出力，含切入/额定/切出三段（rf-006）。"""
    spec = {
        "title": "功率曲线：风速到出力的映射",
        "nodes": [
            {"id": "n1", "label": "切入风速", "kind": "box"},
            {"id": "n2", "label": "额定风速", "kind": "box"},
            {"id": "n3", "label": "切出风速", "kind": "box"},
            {"id": "n4", "label": "有功出力", "kind": "current"},
            {"id": "n5", "label": "损失系数", "kind": "note"},
        ],
        "edges": [
            {"from": "n1", "to": "n4", "label": "上升段", "type": "causes"},
            {"from": "n2", "to": "n4", "label": "额定平台", "type": "causes"},
            {"from": "n3", "to": "n4", "label": "停机", "type": "causes"},
            {"from": "n5", "to": "n4", "label": "修正", "type": "causes"},
        ],
        "steps": [
            {"caption": "低于切入风速：不出力", "show": ["n1", "n4"], "active": "n1"},
            {"caption": "切入至额定：出力随风速上升", "show": ["n1", "n2", "n4"], "active": "n2"},
            {"caption": "达到额定风速：出力维持额定平台", "show": ["n1", "n2", "n4"], "active": "n4"},
            {"caption": "超过切出风速：停机保护，出力降为零", "show": ["n1", "n2", "n3", "n4"], "active": "n3"},
            {"caption": "损失系数（尾流/线损）最终修正有功出力", "show": ["n4", "n5"], "active": "n5"},
        ],
        "game": {
            "type": "sort",
            "goal": "把功率曲线的关键风速点按由低到高排序",
            "items": ["额定风速", "切入风速", "切出风速"],
            "answer": [1, 0, 2],
        },
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


def generate_uncertainty_scene() -> dict | None:
    """不确定性与误差 + 概率区间：误差指标 → 集合预报 → 偏差校正（rf-012/013/014）。"""
    spec = {
        "title": "预测误差与集合预报",
        "nodes": [
            {"id": "n1", "label": "预测误差(RMSE/MAE)", "kind": "current"},
            {"id": "n2", "label": "集合预报", "kind": "box"},
            {"id": "n3", "label": "多成员散布", "kind": "note"},
            {"id": "n4", "label": "偏差校正", "kind": "flow"},
            {"id": "n5", "label": "概率区间", "kind": "flow"},
        ],
        "edges": [
            {"from": "n1", "to": "n2", "label": "量化不确定性", "type": "causes"},
            {"from": "n2", "to": "n3", "label": "产生", "type": "causes"},
            {"from": "n3", "to": "n4", "label": "修正", "type": "prereq"},
            {"from": "n3", "to": "n5", "label": "推得", "type": "causes"},
        ],
        "steps": [
            {"caption": "用 RMSE/MAE 等指标衡量预测偏差", "show": ["n1"], "active": "n1"},
            {"caption": "集合预报以多个成员刻画不确定性范围", "show": ["n1", "n2"], "active": "n2"},
            {"caption": "成员散布反映预测不确定性的大小", "show": ["n1", "n2", "n3"], "active": "n3"},
            {"caption": "偏差校正修正系统偏差，提升精度", "show": ["n1", "n2", "n3", "n4"], "active": "n4"},
            {"caption": "从成员散布推得概率区间用于调度决策", "show": ["n1", "n2", "n3", "n4", "n5"], "active": "n5"},
        ],
        "game": {
            "type": "sort",
            "goal": "把不确定性治理链条按正确顺序排列",
            "items": ["偏差校正", "误差量化", "集合预报"],
            "answer": [1, 2, 0],
        },
    }
    verdict, norm = check_scene(spec)
    return norm if verdict else None


DOMAIN_ID = "renewable_forecasting"

#: Template concept ID (``rf-*``) -> curated scene generator.  Asset concept
#: IDs and concept names are normalized onto these IDs by
#: ``domain_templates.resolve_template_concept_id``.
SCENE_GENERATORS: dict[str, callable] = {
    "rf-001": generate_forecast_horizons_scene,
    "rf-002": generate_forecast_horizons_scene,
    "rf-003": generate_forecast_horizons_scene,
    "rf-004": generate_forecast_horizons_scene,
    "rf-005": generate_nwp_driver_scene,
    "rf-006": generate_power_curve_scene,
    "rf-008": generate_nwp_driver_scene,
    "rf-012": generate_uncertainty_scene,
    "rf-013": generate_uncertainty_scene,
    "rf-014": generate_uncertainty_scene,
}


def scene_for_concept_id(template_concept_id: str) -> dict | None:
    """Curated scene for a template concept ID, or None when there is none."""
    generator = SCENE_GENERATORS.get(str(template_concept_id or "").strip())
    return generator() if generator else None


def get_scene_for_concept(concept_ref: str, asset=None) -> dict | None:
    """Domain scene for a concept, resolved by template ID, asset ID or name.

    Mirrors ``decoder_electricity.get_scene_for_concept`` /
    ``decoder_carbon.get_scene_for_concept``: resolution is delegated to
    ``domain_templates.resolve_template_concept_id`` so the scene mapping stays
    in sync with ``apply_domain_template``.  Returns None when the concept has
    no curated scene.  Deterministic.
    """
    template_id = resolve_template_concept_id(concept_ref, asset, domain_id=DOMAIN_ID)
    if not template_id:
        return None
    return scene_for_concept_id(template_id)


def domain_scene_for(asset, concept, domain: str | None = None) -> dict | None:
    """Domain scene for a concept of ``asset``, gated on the detected domain.

    Same gate as the electricity/carbon decoders: the domain comes from
    ``domain`` when given, otherwise from ``detect_domain_from_title(asset.title)``
    — a non-renewable asset never picks up renewable visuals just because a
    concept name collides.  Returns None to mean "no domain scene, use generic".
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
