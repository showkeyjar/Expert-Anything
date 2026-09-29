"""Domain-specific knowledge templates.

Provides pre-built concept structures, learning paths, and scene generators
for specific domains. This allows ExpertAnything to skip the first-pass
extraction for well-understood domains and go straight to teaching.

Current domains:
- Electricity trading (China market)
- Carbon emission trading
- Renewable energy forecasting
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any


@dataclass
class DomainTemplate:
    """A pre-built knowledge structure for a specific domain."""
    
    domain_id: str
    name: str
    chapters: list[dict] = field(default_factory=list)
    quick_path: list[str] = field(default_factory=list)
    misconceptions: dict[str, str] = field(default_factory=dict)
    anchor_mapping: dict[str, str] = field(default_factory=dict)
    
    def get_concept_by_id(self, cid: str) -> dict | None:
        for ch in self.chapters:
            for c in ch.get("concepts", []):
                if c.get("id") == cid:
                    return c
        return None
    
    def get_chapter_by_id(self, chid: str) -> dict | None:
        return next((ch for ch in self.chapters if ch.get("id") == chid), None)


# --------------------------------------------------------------------------- #
# Electricity Trading Domain Template
# --------------------------------------------------------------------------- #

ELECTRICITY_TRADING_TEMPLATE = DomainTemplate(
    domain_id="electricity_trading",
    name="中国电力市场交易体系",
    
    chapters=[
        {
            "id": "ch-market",
            "title": "市场架构",
            "concepts": [
                {
                    "id": "et-001",
                    "name": "两级市场架构",
                    "definition": "中国电力市场实行省级市场与区域市场两级运作，分别负责省内和跨省跨区交易组织。",
                    "evidence": ["中国电力市场实行\"两级运作\"架构：省级市场与区域市场。"],
                    "significance": "理解中国电力市场的基本组织形式，是所有后续学习的基础。",
                    "misconceptions": ["省级市场和区域市场是竞争关系", "两级市场各自独立运作"],
                },
                {
                    "id": "et-002",
                    "name": "省级电力交易中心",
                    "definition": "负责省内交易组织的日常运营机构。",
                    "evidence": ["省级电力交易中心：负责省内交易组织的日常运营"],
                    "prerequisites": ["et-001"],
                },
                {
                    "id": "et-003",
                    "name": "中长期交易",
                    "definition": "包括年度、月度、月内交易，是市场主体规避风险的主要手段。",
                    "evidence": ["中长期交易：包括年度、月度、月内交易，是市场主体规避风险的主要手段。"],
                    "connections": ["et-004"],
                },
                {
                    "id": "et-004",
                    "name": "现货交易",
                    "definition": "包括日前市场、日内市场和实时平衡市场，体现电力的实时供需关系。",
                    "evidence": ["现货交易：包括日前市场、日内市场和实时平衡市场，体现电力的实时供需关系。"],
                    "connections": ["et-003"],
                },
            ]
        },
        {
            "id": "ch-player",
            "title": "参与主体",
            "concepts": [
                {
                    "id": "et-005",
                    "name": "发电企业",
                    "definition": "包括火电、水电、核电、风电、光伏等各类电源主体。",
                    "evidence": ["发电企业：包括火电、水电、核电、风电、光伏等各类电源主体。"],
                    "role": "供给方",
                },
                {
                    "id": "et-006",
                    "name": "售电公司",
                    "definition": "作为中间商，代理用户参与市场交易，提供增值服务等。",
                    "evidence": ["售电公司：作为中间商，代理用户参与市场交易，提供增值服务等。"],
                    "misconceptions": ["售电公司自己发电", "售电公司赚取差价"],
                    "role": "中间商",
                },
                {
                    "id": "et-007",
                    "name": "电力用户",
                    "definition": "逐步放开大工业用户、一般工商业用户参与市场交易。",
                    "evidence": ["电力用户：逐步放开大工业用户、一般工商业用户参与市场交易。"],
                    "role": "需求方",
                },
                {
                    "id": "et-008",
                    "name": "电网企业",
                    "definition": "负责输配电服务，收取过网费，不承担差价风险。",
                    "evidence": ["电网企业：负责输配电服务，收取过网费，不承担差价风险。"],
                    "role": "基础设施",
                },
                {
                    "id": "et-009",
                    "name": "调度机构",
                    "definition": "负责电网安全运行，执行发电计划，保障实时平衡。",
                    "evidence": ["调度机构：负责电网安全运行，执行发电计划，保障实时平衡。"],
                    "role": "安全守护者",
                },
            ]
        },
        {
            "id": "ch-price",
            "title": "电价机制",
            "concepts": [
                {
                    "id": "et-010",
                    "name": "上网电价",
                    "definition": "发电企业向电网销售电力的价格，由市场竞争形成或政府核定。",
                    "evidence": ["上网电价：发电企业向电网销售电力的价格，由市场竞争形成或政府核定。"],
                },
                {
                    "id": "et-011",
                    "name": "输配电价",
                    "definition": "电网企业提供输配电服务的价格，实行政府定价。",
                    "evidence": ["输配电价：电网企业提供输配电服务的价格，实行政府定价。"],
                    "misconceptions": ["输配电价是市场形成的", "输配电价包含利润空间"],
                },
                {
                    "id": "et-012",
                    "name": "销售电价",
                    "definition": "电力用户最终支付的价格，由上网电价+输配电价+政府基金构成。",
                    "evidence": ["销售电价：电力用户最终支付的价格，由上网电价+输配电价+政府基金构成。"],
                },
                {
                    "id": "et-013",
                    "name": "节点边际电价(LMP)",
                    "definition": "反映电网不同位置的供电边际成本，包含电能价值、阻塞成本和网损成本。",
                    "evidence": ["节点边际电价（LMP）：反映电网不同位置的供电边际成本，包含电能价值、阻塞成本和网损成本。"],
                    "significance": "现货市场的核心定价机制，理解LMP是掌握电力市场的关键。",
                },
            ]
        },
        {
            "id": "ch-process",
            "title": "交易流程",
            "concepts": [
                {
                    "id": "et-014",
                    "name": "中长期交易流程",
                    "definition": "签订合约→履约结算→偏差调整。",
                    "evidence": ["中长期交易流程：签订合约→履约结算→偏差调整。"],
                    "steps": ["签订合约", "履约结算", "偏差调整"],
                },
                {
                    "id": "et-015",
                    "name": "日前市场流程",
                    "definition": "发电报价→负荷预测→出清计算→发布结果。",
                    "evidence": ["日前市场流程：发电报价→负荷预测→出清计算→发布结果。"],
                    "steps": ["发电报价", "负荷预测", "出清计算", "发布结果"],
                },
                {
                    "id": "et-016",
                    "name": "实时平衡流程",
                    "definition": "滚动预测→偏差处理→调度执行→费用结算。",
                    "evidence": ["实时平衡流程：滚动预测→偏差处理→调度执行→费用结算。"],
                    "steps": ["滚动预测", "偏差处理", "调度执行", "费用结算"],
                },
            ]
        },
        {
            "id": "ch-concept",
            "title": "关键概念辨析",
            "concepts": [
                {
                    "id": "et-017",
                    "name": "容量电费",
                    "definition": "反映固定成本回收的电费组成部分。",
                    "evidence": ["容量电费 vs 电量电费：容量电费反映固定成本回收，电量电费反映可变成本与边际定价。"],
                    "connections": ["et-018"],
                },
                {
                    "id": "et-018",
                    "name": "电量电费",
                    "definition": "反映可变成本与边际定价的电费组成部分。",
                    "evidence": ["容量电费 vs 电量电费：容量电费反映固定成本回收，电量电费反映可变成本与边际定价。"],
                    "connections": ["et-017"],
                },
                {
                    "id": "et-019",
                    "name": "不平衡资金",
                    "definition": "市场出清过程中因预测偏差、约束调整等产生的资金盈余或短缺。",
                    "evidence": ["不平衡资金：市场出清过程中因预测偏差、约束调整等产生的资金盈余或短缺。"],
                    "significance": "现货市场结算的关键问题，理解如何分摊不平衡成本。",
                },
            ]
        },
    ],
    
    quick_path=["et-001", "et-005", "et-007", "et-010", "et-011", "et-012", "et-013"],
    
    misconceptions={
        "输电价格": "输配电价是政府定价，不是市场形成",
        "现货价格": "现货价格是实时供需的结果，不是预测值",
        "售电公司": "售电公司不发电，只做代理和增值服务",
        "两级市场": "省级和区域市场是协作关系，不是竞争关系",
    },
    
    anchor_mapping={
        "carbon": "碳排放权交易与电力市场的耦合机制",
        "forecast": "负荷预测在日前市场中的核心作用",
        "remote": "遥感数据在新能源出力预测中的应用",
        "wind": "风电出力不确定性对现货市场的影响",
    }
)


# --------------------------------------------------------------------------- #
# Carbon Trading Domain Template (second domain — reusability check)
# --------------------------------------------------------------------------- #
# Second registered domain, added to prove the Phase 3 domain mechanism is
# *reusable* and not electricity-specific: template -> registry -> title
# detection -> prompt-key suffix -> skeleton injection all work unchanged.
#
# Content policy for this skeleton (stricter than the electricity template):
# only textbook-level, time-invariant notions of emissions trading are encoded
# (cap, allowance, allocation, compliance cycle, offset, MRV, oversight ...).
# It deliberately contains NO numeric values, NO specific policy clauses and
# NO time-sensitive facts.  Every ``evidence`` entry is prefixed with
# ``【示意】`` to mark it explicitly as illustrative template text rather than
# a quotation from any real document — template evidence is only ever written
# into concepts that have none of their own (see ``apply_domain_template``).

CARBON_TRADING_TEMPLATE = DomainTemplate(
    domain_id="carbon_trading",
    name="碳排放权交易体系",

    chapters=[
        {
            "id": "ch-cap",
            "title": "总量与配额制度",
            "concepts": [
                {
                    "id": "ct-001",
                    "name": "总量控制",
                    "definition": "对一定时期内允许排放的温室气体总量设定上限的制度安排。",
                    "evidence": ["【示意】总量控制：对一定时期内允许排放的温室气体总量设定上限。"],
                    "significance": "碳排放权交易制度的前提，决定了配额的稀缺程度。",
                    "misconceptions": ["总量控制等于对单个企业的排放量直接下达指令"],
                },
                {
                    "id": "ct-002",
                    "name": "碳排放配额",
                    "aliases": ["配额", "排放配额"],
                    "definition": "总量控制下向排放单位分配或发放的排放许可额度。",
                    "evidence": ["【示意】碳排放配额：总量控制下分配或发放给排放单位的排放许可额度。"],
                    "prerequisites": ["ct-001"],
                    "misconceptions": ["配额是一种税收", "持有配额即已完成合规义务"],
                },
                {
                    "id": "ct-003",
                    "name": "配额分配方式",
                    "definition": "配额初始配置方法的统称，包括免费分配与有偿拍卖两类。",
                    "evidence": ["【示意】配额分配方式：包括免费分配（如历史法、基准线法）与有偿拍卖等。"],
                    "prerequisites": ["ct-002"],
                    "connections": ["ct-005"],
                },
                {
                    "id": "ct-004",
                    "name": "履约周期",
                    "definition": "排放单位完成排放核算、报告、核查与配额清缴的合规时间安排。",
                    "evidence": ["【示意】履约周期：排放单位完成核算、报告、核查与配额清缴的时间安排。"],
                    "prerequisites": ["ct-002"],
                    "connections": ["ct-009"],
                },
            ]
        },
        {
            "id": "ch-market",
            "title": "市场与交易机制",
            "concepts": [
                {
                    "id": "ct-005",
                    "name": "碳排放权交易市场",
                    "definition": "以配额为主要交易标的、由排放单位等主体参与的交易体系。",
                    "evidence": ["【示意】碳排放权交易市场：以配额为主要标的、多方主体参与的交易体系。"],
                    "prerequisites": ["ct-002"],
                    "connections": ["ct-006"],
                },
                {
                    "id": "ct-006",
                    "name": "碳价形成",
                    "definition": "由配额供需、政策预期与减排成本共同作用形成的价格信号。",
                    "evidence": ["【示意】碳价形成：由配额供需、政策预期与减排成本共同作用形成。"],
                    "prerequisites": ["ct-005"],
                    "misconceptions": ["碳价由政府直接固定", "碳价只反映当期配额存量"],
                },
                {
                    "id": "ct-007",
                    "name": "抵消机制",
                    "definition": "允许以符合条件的减排量抵销部分履约义务的机制安排。",
                    "evidence": ["【示意】抵消机制：允许以符合条件的减排量抵销部分履约义务。"],
                    "prerequisites": ["ct-002"],
                    "connections": ["ct-008"],
                    "misconceptions": ["抵消机制可以完全替代配额清缴", "抵消机制没有使用范围限制"],
                },
                {
                    "id": "ct-008",
                    "name": "自愿减排量",
                    "definition": "经核证的自愿减排项目所产生的减排量，可按规定用于抵消。",
                    "evidence": ["【示意】自愿减排量：经核证的自愿减排项目产生的减排量。"],
                    "prerequisites": ["ct-007"],
                    "connections": ["ct-010"],
                },
            ]
        },
        {
            "id": "ch-mrv",
            "title": "监测报告核查",
            "concepts": [
                {
                    "id": "ct-009",
                    "name": "MRV 监测-报告-核查",
                    "aliases": ["MRV", "监测报告核查"],
                    "definition": "对排放数据实施监测、报告与第三方核查的制度安排。",
                    "evidence": ["【示意】MRV：监测（Monitoring）、报告（Reporting）与核查（Verification）的制度安排。"],
                    "significance": "碳市场数据可信度的基础，也是配额清缴的依据。",
                    "prerequisites": ["ct-004"],
                    "misconceptions": ["MRV 是一次性的检测报告", "MRV 只由排放单位自行完成"],
                },
                {
                    "id": "ct-010",
                    "name": "排放核算方法",
                    "definition": "核算温室气体排放量所依据的方法学统称。",
                    "evidence": ["【示意】排放核算方法：如排放因子法、质量平衡法等核算方法学。"],
                    "prerequisites": ["ct-009"],
                },
                {
                    "id": "ct-011",
                    "name": "核查机构",
                    "definition": "独立于排放单位、承担排放数据核查职责的第三方主体。",
                    "evidence": ["【示意】核查机构：独立于排放单位、承担数据核查职责的第三方。"],
                    "prerequisites": ["ct-009"],
                    "contains": ["ct-010"],
                },
            ]
        },
        {
            "id": "ch-oversight",
            "title": "监管与合规",
            "concepts": [
                {
                    "id": "ct-012",
                    "name": "碳市场监管",
                    "definition": "主管部门对配额发放、交易行为与信息披露的管理与监督。",
                    "evidence": ["【示意】碳市场监管：主管部门对配额发放、交易与信息披露的管理监督。"],
                    "prerequisites": ["ct-005"],
                },
                {
                    "id": "ct-013",
                    "name": "合规风险",
                    "definition": "未按期履约、数据不实等情形给市场主体带来的处罚与信用风险。",
                    "evidence": ["【示意】合规风险：未按期履约、数据不实等导致的处罚与信用风险。"],
                    "prerequisites": ["ct-004", "ct-009"],
                },
            ]
        },
    ],

    quick_path=["ct-001", "ct-002", "ct-003", "ct-004", "ct-005", "ct-006", "ct-009"],

    misconceptions={
        "碳排放配额": "配额是排放许可，不是税收；持有配额不等于已完成合规义务",
        "碳价": "碳价由配额供需与政策预期等共同形成，不是政府直接固定的价格",
        "抵消机制": "抵消机制是履约的补充手段，通常设有使用范围限制，不能完全替代配额",
        "MRV": "MRV 是监测-报告-核查的制度安排，不是单次检测或一份报告",
    },

    anchor_mapping={
        "power": "电力等纳入行业在碳市场中的排放核算定位",
        "coal": "化石燃料消耗与排放核算方法的衔接",
        "ccus": "碳捕集利用与封存技术在减排量核算中的定位",
        "green": "绿电、绿证与碳市场机制的衔接关系",
    }
)


# --------------------------------------------------------------------------- #
# Domain Registry
# --------------------------------------------------------------------------- #

DOMAIN_TEMPLATES: dict[str, DomainTemplate] = {
    "electricity_trading": ELECTRICITY_TRADING_TEMPLATE,
    "carbon_trading": CARBON_TRADING_TEMPLATE,
}


def get_domain_template(domain_id: str) -> DomainTemplate | None:
    """Get a domain template by ID."""
    return DOMAIN_TEMPLATES.get(domain_id)


#: Keyword tables used by :func:`detect_domain_from_title`, ordered by
#: specificity so that two domains can never bleed into each other.
#:
#: ``_STRONG_POWER_KEYWORDS`` are unambiguous electricity-market terms.
#: ``_WEAK_POWER_KEYWORDS`` ("交易市场" alone) is a generic phrase that also
#: appears in carbon titles ("碳排放权交易市场"), so it is only consulted after
#: the carbon table — otherwise a carbon asset would be captured by the
#: electricity template.  Conversely a title naming power *and* carbon
#: ("电力行业碳排放核算") stays on the electricity side, which is the historical
#: behaviour and keeps the electricity template's ``carbon`` anchor relevant.
_STRONG_POWER_KEYWORDS = ("电力", "电网", "电价", "spot market", "electricity")
_WEAK_POWER_KEYWORDS = ("交易市场",)
_CARBON_KEYWORDS = ("碳", "carbon", "emission", "排放")


def detect_domain_from_title(title: str) -> str | None:
    """Try to detect domain from asset title.

    Deterministic keyword matching, strongest signal first: strong power terms,
    then carbon terms, then the weak/generic power phrase.  Returns ``None``
    when nothing matches, which callers treat as "no domain" (generic prompts).
    """
    title_lower = str(title or "").lower()

    if any(kw in title_lower for kw in _STRONG_POWER_KEYWORDS):
        return "electricity_trading"

    if any(kw in title_lower for kw in _CARBON_KEYWORDS):
        return "carbon_trading"

    if any(kw in title_lower for kw in _WEAK_POWER_KEYWORDS):
        return "electricity_trading"

    return None


#: Minimum share of template concepts that must find a home in the asset
#: before the template's quick path is allowed to replace the asset's path.
DEFAULT_MIN_COVERAGE = 0.5


def template_concept_skeleton(template: DomainTemplate | None) -> str:
    """Render a domain template's concept skeleton as prompt-injectable text.

    One line per chapter: ``- <章节>: <概念名>（<模板ID>）[别名: ...]``.  This is
    used by the domain-specific extraction/teacher prompts (Phase 3) purely as
    *alignment guidance* — the skeleton tells the model which concepts this
    domain normally contains and how they are canonically named.  It is never a
    knowledge source: prompts receiving it must still drop any concept absent
    from the source text (see docs/电力交易领域学习方案.md).

    Returns ``""`` for ``None`` or a template without concepts, so callers can
    inject the result unconditionally.
    """
    if template is None:
        return ""
    lines: list[str] = []
    for ch in template.chapters or []:
        labels: list[str] = []
        for c in ch.get("concepts", []) or []:
            name = str(c.get("name") or "").strip()
            if not name:
                continue
            cid = str(c.get("id") or "").strip()
            label = f"{name}（{cid}）" if cid else name
            aliases = [str(a).strip() for a in (c.get("aliases") or []) if str(a).strip()]
            if aliases:
                label += f"[别名: {'/'.join(aliases)}]"
            labels.append(label)
        if labels:
            chapter = str(ch.get("title") or ch.get("id") or "").strip()
            lines.append(f"- {chapter}: " + "、".join(labels))
    return "\n".join(lines)


def domain_concept_skeleton(domain_id: str | None) -> str:
    """Concept skeleton of a registered domain, ``""`` when unknown."""
    if not domain_id:
        return ""
    return template_concept_skeleton(get_domain_template(domain_id))


def domain_concept_names(domain_id: str | None) -> list[str]:
    """All concept names declared by a domain template (``[]`` when unknown)."""
    template = get_domain_template(domain_id) if domain_id else None
    if template is None:
        return []
    return [
        str(c.get("name")).strip()
        for ch in template.chapters or []
        for c in (ch.get("concepts") or [])
        if str(c.get("name") or "").strip()
    ]


def _normalize_name(name: str) -> str:
    """Normalize a concept name into a matching key.

    Mirrors ``learner.normalize`` (NFKC → lowercase → collapse separators →
    drop punctuation) so template names and asset names compare on equal
    footing, whatever bracket style or spacing the source used.
    """
    s = unicodedata.normalize("NFKC", str(name or "")).lower().strip()
    s = re.sub(r"[\s\-_/]+", " ", s)
    s = re.sub(r"[^\w\s]", "", s, flags=re.UNICODE)
    return s.strip()


_PARENTHETICAL_RE = re.compile(r"[（(\[【]([^）)\]】]*)[）)\]】]")


def concept_name_variants(name: str) -> set[str]:
    """All normalized spellings of a name that may appear in an asset.

    ``节点边际电价(LMP)`` yields three variants: the full spelling, the
    spelling without the parenthetical part (``节点边际电价``) and the
    parenthetical body itself (``lmp``) — the last only when it carries two or
    more characters, since single letters are too ambiguous to match on.
    """
    raw = unicodedata.normalize("NFKC", str(name or ""))
    variants: set[str] = set()
    for candidate in (raw, _PARENTHETICAL_RE.sub(" ", raw)):
        value = _normalize_name(candidate)
        if value:
            variants.add(value)
    for inner in _PARENTHETICAL_RE.findall(raw):
        value = _normalize_name(inner)
        if len(value) >= 2:
            variants.add(value)
    return variants


def _template_concept_variants(data: dict) -> set[str]:
    """Variants of a template concept, including any declared ``aliases``."""
    variants = concept_name_variants(data.get("name", ""))
    for alias in data.get("aliases") or []:
        variants |= concept_name_variants(alias)
    return variants


def build_concept_mapping(asset, template: DomainTemplate) -> dict:
    """Map template concept IDs onto asset concept IDs, by name.

    Deterministic and ID-agnostic: concepts are matched through normalized
    name/alias variants only.  Each asset concept is claimed at most once
    (first template concept in template order wins), and a template concept
    that matches nothing is reported in ``unmatched`` instead of being
    silently dropped.

    Returns a report dict:
    ``{"mapping", "details", "unmatched", "template_concept_count",
    "matched_count", "coverage"}``.
    """
    index: dict[str, list[str]] = {}
    for concept in getattr(asset, "concepts", None) or []:
        for variant in concept_name_variants(getattr(concept, "name", "")):
            index.setdefault(variant, []).append(concept.id)

    mapping: dict[str, str] = {}
    details: list[dict] = []
    unmatched: list[str] = []
    claimed: set[str] = set()
    total = 0

    for chapter in template.chapters:
        for data in chapter.get("concepts", []) or []:
            tid = data.get("id")
            if not tid:
                continue
            total += 1
            # Longest (most specific) variant first, then lexicographic —
            # a full-name hit beats a loose parenthetical alias.
            hit = ""
            for variant in sorted(_template_concept_variants(data),
                                  key=lambda v: (-len(v), v)):
                for cid in index.get(variant, []):
                    if cid not in claimed:
                        hit = cid
                        break
                if hit:
                    break
            if not hit:
                unmatched.append(tid)
                continue
            claimed.add(hit)
            mapping[tid] = hit
            matched = asset.concept_by_id(hit)
            details.append({
                "template_id": tid,
                "template_name": data.get("name", ""),
                "asset_id": hit,
                "asset_name": getattr(matched, "name", ""),
                "enriched_fields": [],
            })

    return {
        "mapping": mapping,
        "details": details,
        "unmatched": unmatched,
        "template_concept_count": total,
        "matched_count": len(mapping),
        "coverage": (len(mapping) / total) if total else 0.0,
    }


def _template_name_index(template: DomainTemplate) -> dict[str, str]:
    """Normalized name/alias variant -> template concept ID.

    Built in template order and filled with ``setdefault``, so the first
    concept declaring a variant owns it — the same "template order wins"
    determinism ``build_concept_mapping`` uses.
    """
    index: dict[str, str] = {}
    for chapter in template.chapters:
        for data in chapter.get("concepts", []) or []:
            tid = data.get("id")
            if not tid:
                continue
            for variant in _template_concept_variants(data):
                index.setdefault(variant, tid)
    return index


def resolve_template_concept_id(concept_ref, asset=None,
                                domain_id: str = "electricity_trading") -> str:
    """Resolve any concept reference to a template concept ID (``et-*``).

    Three deterministic routes, tried in order:

    1. **template concept ID** — ``et-001`` is returned as-is when the
       template knows it;
    2. **asset concept ID** — ``c001`` is looked up on ``asset`` and resolved
       through that concept's *name*, which is what finally lines the asset
       ID space up with the template ID space;
    3. **concept name** — any normalized spelling: the full name, the name
       without its parenthetical part, or the parenthetical body itself
       (``节点边际电价`` / ``节点边际电价(LMP)`` / ``LMP``), insensitive to
       case, width and separators.

    ``asset`` is optional but required for route 2.  Returns ``""`` when
    nothing matches, so callers fall back instead of guessing.  Pure name
    normalisation — no LLM, no network.
    """
    ref = str(concept_ref or "").strip()
    if not ref:
        return ""
    template = get_domain_template(domain_id)
    if template is None:
        return ""

    # Route 1: the reference is already a template concept ID.
    if template.get_concept_by_id(ref) is not None:
        return ref

    # Route 2: the reference is an asset concept ID — resolve by its name.
    # Route 3: the reference is a concept name already.
    names = [ref]
    if asset is not None:
        concept = asset.concept_by_id(ref)
        if concept is not None:
            name = getattr(concept, "name", "") or ""
            names = [name] if name else []

    index = _template_name_index(template)
    for name in names:
        # Longest (most specific) variant first — a full-name hit beats a
        # loose parenthetical alias, mirroring build_concept_mapping.
        for variant in sorted(concept_name_variants(name),
                              key=lambda v: (-len(v), v)):
            tid = index.get(variant)
            if tid:
                return tid
    return ""


@dataclass
class TemplateApplicationResult:
    """Outcome of :func:`apply_domain_template`, rich enough for the UI.

    ``bool(result)`` is True whenever a template was found and applied — even
    if its learning path had to be skipped.  Inspect ``learning_path_applied``
    / ``degraded`` / ``reason`` for the fine-grained verdict:

    ``ok``                   template applied and learning path rewritten
    ``degraded_no_mapping``  no template concept matched the asset
    ``degraded_low_coverage``coverage below ``min_coverage``
    ``unknown_domain``       no template registered for that domain
    """

    domain_id: str
    template_name: str = ""
    applied: bool = False
    reason: str = ""
    concept_mapping: dict[str, str] = field(default_factory=dict)
    mapping_details: list[dict] = field(default_factory=list)
    unmatched_template_concepts: list[str] = field(default_factory=list)
    template_concept_count: int = 0
    matched_count: int = 0
    coverage: float = 0.0
    enriched_count: int = 0
    learning_path_applied: bool = False
    learning_path: list[str] = field(default_factory=list)

    @property
    def degraded(self) -> bool:
        """True when the template applied but the learning path was skipped."""
        return self.applied and not self.learning_path_applied

    def __bool__(self) -> bool:
        return self.applied

    def to_dict(self) -> dict:
        return {
            "domain_id": self.domain_id,
            "template_name": self.template_name,
            "applied": self.applied,
            "reason": self.reason,
            "degraded": self.degraded,
            "concept_mapping": dict(self.concept_mapping),
            "mapping_details": [dict(d) for d in self.mapping_details],
            "unmatched_template_concepts": list(self.unmatched_template_concepts),
            "template_concept_count": self.template_concept_count,
            "matched_count": self.matched_count,
            "coverage": self.coverage,
            "enriched_count": self.enriched_count,
            "learning_path_applied": self.learning_path_applied,
            "learning_path": list(self.learning_path),
        }


def apply_domain_template(asset, domain_id: str, *,
                          min_coverage: float = DEFAULT_MIN_COVERAGE
                          ) -> TemplateApplicationResult:
    """Apply a domain template to an existing asset.

    Enrichment is **name driven**: template concepts are mapped onto asset
    concepts by normalized name / alias (see :func:`build_concept_mapping`),
    never by ID — extracted assets use ``c*`` sequential IDs while template
    concepts are ``et-*``, so an ID lookup can never hit.  Only matched
    concepts are enriched, and ``definition`` / ``evidence`` are filled only
    when the asset has none: extracted, source-grounded text is never
    overwritten by template text.

    ``template.quick_path`` is written to ``asset.learning_path`` **only** when
    every entry survives the mapping (each resulting ID is re-checked against
    ``asset.concepts``) *and* ``coverage >= min_coverage``.  Otherwise the
    original path is left untouched and the result carries the degraded signal
    (``learning_path_applied=False`` plus an explanatory ``reason``) along with
    the full mapping statistics for the UI.

    Truthiness keeps the historic contract: ``bool(result)`` is False only when
    no template is registered for the domain.
    """
    template = get_domain_template(domain_id)
    if not template:
        return TemplateApplicationResult(
            domain_id=domain_id,
            reason="unknown_domain",
            applied=False,
            learning_path=list(getattr(asset, "learning_path", None) or []),
        )

    report = build_concept_mapping(asset, template)

    # --- enrich matched concepts only (never overwrite grounded content) ---
    enriched_count = 0
    for detail in report["details"]:
        concept = asset.concept_by_id(detail["asset_id"])
        if concept is None:  # pragma: no cover - defensive
            continue
        data = template.get_concept_by_id(detail["template_id"]) or {}
        if not concept.definition and data.get("definition"):
            concept.definition = data["definition"]
            detail["enriched_fields"].append("definition")
        if not concept.evidence and data.get("evidence"):
            concept.evidence = list(data["evidence"])
            detail["enriched_fields"].append("evidence")
        if detail["enriched_fields"]:
            enriched_count += 1

    # Template evidence is a paraphrase most of the time, but when the source
    # genuinely contains the sentence we want the provenance badge to anchor.
    # Stamping is idempotent and misses silently (no locations → no badge).
    from expert_anything.core.extraction import _stamp_locations  # local: cycle

    _stamp_locations(asset)

    # --- learning path: map first, then re-verify against the asset ---
    mapped_path: list[str] = []
    for tid in template.quick_path or []:
        cid = report["mapping"].get(tid)
        if cid and cid not in mapped_path and asset.concept_by_id(cid) is not None:
            mapped_path.append(cid)

    result = TemplateApplicationResult(
        domain_id=template.domain_id,
        template_name=template.name,
        applied=True,
        reason="ok",
        concept_mapping=dict(report["mapping"]),
        mapping_details=report["details"],
        unmatched_template_concepts=report["unmatched"],
        template_concept_count=report["template_concept_count"],
        matched_count=report["matched_count"],
        coverage=report["coverage"],
        enriched_count=enriched_count,
        learning_path=list(getattr(asset, "learning_path", None) or []),
    )

    if not mapped_path:
        result.reason = "degraded_no_mapping"
        return result
    if report["coverage"] < min_coverage:
        result.reason = "degraded_low_coverage"
        return result

    asset.learning_path = mapped_path
    result.learning_path_applied = True
    result.learning_path = list(mapped_path)
    return result
