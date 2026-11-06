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
# Renewable Energy Power Forecasting Domain Template (third domain)
# --------------------------------------------------------------------------- #
# Third registered domain.  Mirrors the electricity/carbon templates: textbook-
# level, time-invariant engineering notions of renewable power forecasting
# (forecast horizons, NWP drivers, power curve, wind/PV/load targets, error
# metrics, ensemble forecasting, bias correction).  No numeric thresholds, no
# vendor specifics — only the stable skeleton a learner needs before reading a
# real forecast report.  Template ``evidence`` is plain paraphrase (like the
# electricity template, since the content is engineering fundamentals, not
# time-sensitive policy) and is only ever written into concepts that have none
# of their own.

RENEWABLE_FORECASTING_TEMPLATE = DomainTemplate(
    domain_id="renewable_forecasting",
    name="新能源功率预测体系",

    chapters=[
        {
            "id": "ch-horizon",
            "title": "预测尺度与时间轴",
            "concepts": [
                {
                    "id": "rf-001",
                    "name": "超短期预测",
                    "definition": "对未来数分钟至4小时内的新能源出力进行滚动预测，时间分辨率通常为15分钟。",
                    "evidence": ["超短期预测：对未来数分钟至4小时内的新能源出力滚动预测，时间分辨率通常为15分钟。"],
                    "significance": "面向实时调度与AGC，是平抑波动、保障安全的第一道防线。",
                    "misconceptions": ["超短期预测用于年度规划", "超短期预测可以替代日前市场"],
                },
                {
                    "id": "rf-002",
                    "name": "短期预测",
                    "definition": "以日前预测为主，覆盖未来0至72小时的新能源出力预测，是电力调度与市场交易的主要依据。",
                    "evidence": ["短期预测：以日前预测为主，覆盖未来0至72小时的新能源出力预测。"],
                    "prerequisites": ["rf-001"],
                    "connections": ["rf-003"],
                },
                {
                    "id": "rf-003",
                    "name": "中长期预测",
                    "definition": "覆盖未来数日至数月的新能源出力趋势预测，服务于检修计划与电量平衡。",
                    "evidence": ["中长期预测：覆盖未来数日至数月的新能源出力趋势预测，服务于检修计划与电量平衡。"],
                    "prerequisites": ["rf-002"],
                    "connections": ["rf-004"],
                },
                {
                    "id": "rf-004",
                    "name": "预测时间尺度",
                    "definition": "按预测周期把预测任务划分为超短期、短期与中长期三类的分类框架。",
                    "evidence": ["预测时间尺度：按预测周期划分为超短期、短期与中长期三类的分类框架。"],
                    "prerequisites": ["rf-001", "rf-002", "rf-003"],
                    "significance": "不同尺度服务不同决策，尺度错配是预测误用的常见根源。",
                },
            ]
        },
        {
            "id": "ch-input",
            "title": "输入与驱动因素",
            "concepts": [
                {
                    "id": "rf-005",
                    "name": "数值天气预报(NWP)",
                    "aliases": ["NWP", "数值天气预报"],
                    "definition": "基于大气物理方程对风速、辐照、温度等气象要素的未来状态进行网格化预报，是功率预测的核心输入。",
                    "evidence": ["数值天气预报（NWP）：基于大气物理方程对风速、辐照、温度等未来状态进行网格化预报，是功率预测的核心输入。"],
                    "significance": "NWP的网格分辨率与更新频率直接决定预测上限。",
                    "misconceptions": ["NWP是实测数据", "NWP分辨率越高越好而无需考虑时延"],
                },
                {
                    "id": "rf-006",
                    "name": "功率曲线",
                    "definition": "描述单机或场站有功出力与风速（光伏为辐照）之间对应关系的特征曲线，是物理建模的基础。",
                    "evidence": ["功率曲线：描述有功出力与风速（光伏为辐照）之间对应关系的特征曲线，是物理建模的基础。"],
                    "prerequisites": ["rf-005"],
                    "misconceptions": ["功率曲线是电价曲线", "功率曲线在所有工况下恒定不变"],
                },
                {
                    "id": "rf-007",
                    "name": "历史出力数据",
                    "definition": "来自SCADA的历史功率与工况记录，用于数据驱动模型的训练与校验。",
                    "evidence": ["历史出力数据：来自SCADA的历史功率与工况记录，用于数据驱动模型的训练与校验。"],
                    "prerequisites": ["rf-006"],
                },
                {
                    "id": "rf-008",
                    "name": "气象要素",
                    "aliases": ["风速", "辐照", "温度"],
                    "definition": "影响新能源出力的关键变量，包括风速、太阳辐照与温度等。",
                    "evidence": ["气象要素：影响新能源出力的关键变量，包括风速、太阳辐照与温度等。"],
                    "connections": ["rf-005", "rf-006"],
                },
            ]
        },
        {
            "id": "ch-target",
            "title": "预测对象",
            "concepts": [
                {
                    "id": "rf-009",
                    "name": "风电功率预测",
                    "definition": "对风电场有功出力的预测，受风速波动与尾流效应显著影响。",
                    "evidence": ["风电功率预测：对风电场有功出力的预测，受风速波动与尾流效应显著影响。"],
                    "prerequisites": ["rf-006"],
                    "connections": ["rf-011"],
                },
                {
                    "id": "rf-010",
                    "name": "光伏功率预测",
                    "definition": "对光伏电站出力的预测，受云团移动与辐照变化主导。",
                    "evidence": ["光伏功率预测：对光伏电站出力的预测，受云团移动与辐照变化主导。"],
                    "prerequisites": ["rf-006"],
                    "connections": ["rf-011"],
                },
                {
                    "id": "rf-011",
                    "name": "负荷预测",
                    "definition": "对用电侧功率需求的预测，与新能源预测共同支撑电力平衡。",
                    "evidence": ["负荷预测：对用电侧功率需求的预测，与新能源预测共同支撑电力平衡。"],
                    "prerequisites": ["rf-009", "rf-010"],
                },
            ]
        },
        {
            "id": "ch-uncertainty",
            "title": "不确定性与误差",
            "concepts": [
                {
                    "id": "rf-012",
                    "name": "预测误差",
                    "aliases": ["RMSE", "MAE"],
                    "definition": "用RMSE、MAE等指标衡量预测值与真实出力之间的偏差，是模型评估的核心。",
                    "evidence": ["预测误差：用RMSE、MAE等指标衡量预测值与真实出力之间的偏差，是模型评估的核心。"],
                    "prerequisites": ["rf-009"],
                    "misconceptions": ["单一误差指标足以评价预测质量", "误差小等于预测可用"],
                },
                {
                    "id": "rf-013",
                    "name": "集合预报",
                    "definition": "由多个成员预报构成、用以刻画预测不确定性的预报方式。",
                    "evidence": ["集合预报：由多个成员预报构成、用以刻画预测不确定性的预报方式。"],
                    "prerequisites": ["rf-012"],
                    "connections": ["rf-014"],
                    "misconceptions": ["集合预报是多个互相矛盾的结果", "集合成员越多越准"],
                },
                {
                    "id": "rf-014",
                    "name": "偏差校正",
                    "definition": "对原始预报的系统偏差进行修正的方法，提升预测精度。",
                    "evidence": ["偏差校正：对原始预报的系统偏差进行修正的方法，提升预测精度。"],
                    "prerequisites": ["rf-013"],
                },
            ]
        },
    ],

    quick_path=["rf-004", "rf-005", "rf-006", "rf-009", "rf-010", "rf-012", "rf-013"],

    misconceptions={
        "功率曲线": "功率曲线是风速到出力的映射，不是电价曲线",
        "超短期预测": "超短期预测面向实时调度，不是年度规划",
        "集合预报": "集合预报表达的是不确定性范围，不是多个互相矛盾的结果",
        "NWP": "NWP是气象数值预报，不是实测数据",
        "预测误差": "误差指标需结合场景解读，单一指标不足以评价预测可用性",
    },

    anchor_mapping={
        "power": "新能源出力与电力系统实时平衡的关系",
        "carbon": "新能源消纳提升与碳减排的关联",
        "market": "新能源预测在日前与现货交易出清中的作用",
        "storage": "预测误差与储能配置规模的关系",
    }
)


# --------------------------------------------------------------------------- #
# Distributed Energy Resources (DER) Domain Template — fourth curated domain.
# --------------------------------------------------------------------------- #

DISTRIBUTED_ENERGY_TEMPLATE = DomainTemplate(
    domain_id="distributed_energy",
    name="分布式能源资源体系",

    chapters=[
        {
            "id": "ch-resource",
            "title": "资源形态",
            "concepts": [
                {
                    "id": "de-001",
                    "name": "分布式发电",
                    "definition": "分布在用户侧或配电网就近的小型发电资源，通常包括分布式光伏、分散式风电、燃气冷热电三联供与生物质发电等。",
                    "evidence": ["分布式发电：分布在用户侧或配电网就近的小型发电资源。"],
                    "significance": "贴近负荷、减少远距离输电损耗，是新型电力系统的重要组成。",
                    "misconceptions": ["分布式发电等同于大型电站分散布置", "分布式发电不需要并网"],
                },
                {
                    "id": "de-002",
                    "name": "分布式光伏",
                    "definition": "利用建筑屋顶、车棚、工商业园区等场地就近安装的光伏发电系统。",
                    "evidence": ["分布式光伏：利用屋顶、车棚等场地就近安装的光伏系统。"],
                    "prerequisites": ["de-001"],
                },
                {
                    "id": "de-003",
                    "name": "分散式风电",
                    "aliases": ["分散式风电", "小型风电"],
                    "definition": "单机容量较小、就近接入配电网的风力发电，区别于集中式大型风电场。",
                    "evidence": ["分散式风电：单机容量较小、就近接入配电网的风力发电。"],
                    "prerequisites": ["de-001"],
                    "connections": ["de-002"],
                },
                {
                    "id": "de-004",
                    "name": "分布式热电与生物质",
                    "definition": "包括燃气冷热电三联供、生物质发电等利用余热与有机质的分布式电源。",
                    "evidence": ["分布式热电与生物质：利用余热与有机质的分布式电源。"],
                    "connections": ["de-001"],
                },
            ]
        },
        {
            "id": "ch-agg",
            "title": "聚合形态",
            "concepts": [
                {
                    "id": "de-005",
                    "name": "微电网",
                    "definition": "由分布式电源、储能、负荷与控制系统构成、可在并网与孤岛两种模式运行的局部电力系统。",
                    "evidence": ["微电网：由分布式电源、储能与负荷构成、可并网或孤岛运行的局部电力系统。"],
                    "prerequisites": ["de-001", "de-002"],
                    "significance": "提升本地供电可靠性与新能源就地消纳能力。",
                    "misconceptions": ["微电网是缩小版大电网", "孤岛运行意味着与大电网永久脱开"],
                },
                {
                    "id": "de-006",
                    "name": "虚拟电厂(VPP)",
                    "aliases": ["VPP", "virtual power plant"],
                    "definition": "通过通信与优化将地理分散的分布式资源聚合为可统一调度的整体。",
                    "evidence": ["虚拟电厂：将分散的分布式资源聚合为可统一调度的整体。"],
                    "prerequisites": ["de-005"],
                    "connections": ["de-007"],
                    "misconceptions": ["虚拟电厂是实体电厂", "VPP只聚合发电不聚合负荷"],
                },
                {
                    "id": "de-007",
                    "name": "需求响应(DR)",
                    "aliases": ["DR", "demand response"],
                    "definition": "通过价格或激励引导用户调整用电时段与负荷水平，等效提供灵活性资源。",
                    "evidence": ["需求响应：引导用户调整用电以等效提供灵活性资源。"],
                    "connections": ["de-006"],
                },
            ]
        },
        {
            "id": "ch-balance",
            "title": "平衡与支撑",
            "concepts": [
                {
                    "id": "de-008",
                    "name": "削峰填谷",
                    "definition": "利用储能与可调负荷在负荷高峰放电、低谷充电，平抑净负荷曲线。",
                    "evidence": ["削峰填谷：高峰放电、低谷充电以平抑净负荷曲线。"],
                    "prerequisites": ["de-005"],
                    "significance": "延缓配网扩容、降低峰谷差价。",
                },
                {
                    "id": "de-009",
                    "name": "就地消纳",
                    "definition": "在分布式电源接入点附近直接消纳其出力，减少倒送与主网传输压力。",
                    "evidence": ["就地消纳：在接入点附近直接消纳出力，减少倒送与主网压力。"],
                    "prerequisites": ["de-002"],
                    "connections": ["de-008"],
                },
                {
                    "id": "de-010",
                    "name": "电压与无功支撑",
                    "definition": "分布式电源与逆变器提供无功调节，维持并网点电压在合格范围。",
                    "evidence": ["电压与无功支撑：分布式电源提供无功调节以维持并网点电压。"],
                    "prerequisites": ["de-002"],
                    "connections": ["de-005"],
                },
            ]
        },
        {
            "id": "ch-value",
            "title": "价值与场景",
            "concepts": [
                {
                    "id": "de-011",
                    "name": "与电网互动",
                    "definition": "分布式资源通过双向计量与调度指令参与配电网运行，形成源网荷储协同。",
                    "evidence": ["与电网互动：分布式资源参与配电网运行，形成源网荷储协同。"],
                    "prerequisites": ["de-005", "de-006"],
                    "connections": ["de-008"],
                },
                {
                    "id": "de-012",
                    "name": "市场化交易",
                    "aliases": ["隔墙售电", "绿电交易"],
                    "definition": "分布式发电可通过隔墙售电、绿电交易等方式向邻近用户市场化售电。",
                    "evidence": ["市场化交易：分布式发电可通过隔墙售电、绿电交易向邻近用户售电。"],
                    "prerequisites": ["de-011"],
                    "misconceptions": ["分布式发电只能自发自用", "绿电交易与常规电无差别"],
                },
                {
                    "id": "de-013",
                    "name": "韧性提升",
                    "definition": "微电网孤岛运行在主网故障时维持关键负荷供电，提升供电韧性。",
                    "evidence": ["韧性提升：微电网孤岛运行在主网故障时维持关键负荷供电。"],
                    "prerequisites": ["de-005"],
                    "connections": ["de-011"],
                },
                {
                    "id": "de-014",
                    "name": "碳减排协同",
                    "definition": "高比例分布式新能源与就地消纳降低输配损耗并替代化石电力，协同碳减排。",
                    "evidence": ["碳减排协同：分布式新能源就地消纳降低损耗并替代化石电力，协同碳减排。"],
                    "prerequisites": ["de-009"],
                    "connections": ["de-012"],
                },
            ]
        },
    ],

    quick_path=["de-001", "de-005", "de-006", "de-008", "de-011", "de-012", "de-013"],

    misconceptions={
        "微电网": "微电网是局部系统，不是缩小版大电网",
        "虚拟电厂": "VPP聚合的是分散资源而非实体电厂",
        "就地消纳": "就地消纳强调就近消耗，不是越多倒送越好",
        "隔墙售电": "隔墙售电是向邻近用户售电，需满足并网与计量规则",
    },

    anchor_mapping={
        "power": "分布式资源与配电网的源网荷储协同关系",
        "carbon": "分布式新能源就地消纳与碳减排的关联",
        "market": "分布式发电隔墙售电与绿电交易的机制",
        "storage": "削峰填谷中储能对分布式平衡的支撑",
        "renewable": "分布式光伏/风电与新能源预测体系的衔接",
    }
)


# --------------------------------------------------------------------------- #
# Domain Registry
# --------------------------------------------------------------------------- #

DOMAIN_TEMPLATES: dict[str, DomainTemplate] = {
    "electricity_trading": ELECTRICITY_TRADING_TEMPLATE,
    "carbon_trading": CARBON_TRADING_TEMPLATE,
    "renewable_forecasting": RENEWABLE_FORECASTING_TEMPLATE,
    "distributed_energy": DISTRIBUTED_ENERGY_TEMPLATE,
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
#: Renewable forecasting keywords.  Kept separate from the power table so a
#: purely renewable title ("风电功率预测") is not hijacked by the electricity
#: template, while a joint title ("电力系统新能源预测") still resolves to
#: electricity via the strong-power branch above.  None of these overlap with
#: the carbon keywords, so the order below is collision-free.
_RENEWABLE_KEYWORDS = ("风电", "光伏", "新能源", "功率预测", "forecast",
                       "renewable", "nwp")
#: Distributed energy resources keywords.  Placed after the renewable table so a
#: purely renewable title ("分布式光伏预测") still resolves to renewable (via the
#: "光伏" branch above), while a DER-specific title ("微电网调度", "虚拟电厂") is
#: captured here.  None of these overlap with the carbon keywords, so the order
#: below is collision-free.  Deliberately avoids "光伏"/"风电"/"新能源" so DER
#: never hijacks a pure renewable asset.
_DER_KEYWORDS = ("分布式能源", "分布式发电", "分布式光伏", "分散式风电",
                 "微电网", "microgrid", "虚拟电厂", "vpp",
                 "demand response", "需求响应", "隔墙售电", "就地消纳",
                 "der", "distributed")
#: Dominant terms that, when present alongside a DER term, win the domain:
#: - power-domain dominants ("电力"/"电价"/electricity/spot market) so a joint
#:   title ("电力系统微电网") resolves to electricity, not DER;
#: - renewable dominants that are NOT substrings of DER concept names
#:   ("功率预测"/"forecast"/"renewable"/"nwp") so a forecasting title
#:   ("分布式光伏功率预测") resolves to renewable, not DER.
#: Deliberately excludes "电网" (substring of "微电网") and "光伏"/"风电"/"新能源"
#: (substrings of DER concept names "分布式光伏"/"分散式风电") — including them
#: would suppress pure-DER titles like "分布式光伏系统" / "分散式风电".
_DER_DOMINANT_GUARD = ("电力", "电价", "electricity", "spot market",
                       "功率预测", "forecast", "renewable", "nwp")


def detect_domain_from_title(title: str) -> str | None:
    """Try to detect domain from asset title.

    Deterministic keyword matching, strongest signal first: strong power terms,
    then renewable terms, then carbon terms, then the weak/generic power phrase.
    Returns ``None`` when nothing matches, which callers treat as "no domain"
    (generic prompts).
    """
    title_lower = str(title or "").lower()

    # DER is checked before the strong-power branch so a purely DER title
    # ("微电网调度") is not hijacked by the "电网" substring inside
    # _STRONG_POWER_KEYWORDS.  It yields to a title that also names a dominant
    # power term ("电力"/"电价"/electricity/spot market) so a joint title
    # ("电力系统微电网") still resolves to electricity, matching the behaviour
    # of the strong-power-over-renewable rule above.
    if any(kw in title_lower for kw in _DER_KEYWORDS):
        if not any(k in title_lower for k in _DER_DOMINANT_GUARD):
            return "distributed_energy"

    if any(kw in title_lower for kw in _STRONG_POWER_KEYWORDS):
        return "electricity_trading"

    if any(kw in title_lower for kw in _RENEWABLE_KEYWORDS):
        return "renewable_forecasting"

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
