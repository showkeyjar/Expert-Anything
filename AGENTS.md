# AGENTS.md

# Project: ExpertAnything — Knowledge Decoder & Learning OS

## Vision
> Make anyone expert in anything — by decoding knowledge into what the learner can see, play and master.

本系统不仅是一个辅助学习系统，更是一个**知识解码与生成系统（Knowledge Decoder & Generator）**：
把书籍/论文/文档中的抽象知识"解译"为图像、动画、互动演示与小游戏，
配合教学-评估-复习闭环，**直到用户完全理解**。

- 知识链路：知识资产 → 知识模型 → 知识解码（多模态表征）→ 学习闭环 → 能力成长
- 解码链路（2026-08 落地）：概念+证据+关系 → **SceneSpec**（LLM 生成的类型化场景规范）
  → `check_scene` 代码准入校验 → 确定性渲染器（分步动画 SVG / 互动 HTML 演示+排序游戏）
  → 理解验证（游戏得分记入掌握度）。见 `core/decoder.py` 与 `docs/Knowledge_Decoder.md`。
- 解码铁律（延续来源约束）：场景中的节点/步骤必须源于概念证据与关系，
  LLM 只产出结构规范，**渲染由确定性代码完成**（开放推理 + 确定性外壳）。

Core principle: optimize for **"Does the user learn?"**, not "Can the AI answer?".
Do not build a simple RAG chatbot.

## 当前产品形态（2026-08 稳定基线）

- **桌面端 PySide6**（`main.py` 入口，`python app.py` 或 `python main.py`），7 个视图：
  导入知识资产 / 知识模型 / 概念网络 / 阅读原文 / 教学会话 / 学习者模型 / 教师模型
- **UI 三区框架**：顶部功能栏（当前资产 + 掌握度进度 + 快捷动作 + 语言切换）+
  左侧导航区 + 中央展示区（视图 header 统一白底蓝条）
- **多语言**：中文 / English / 日本語，`core/i18n.py` 的 `t()` 全量接入，
  **禁止硬编码 UI 文本**（新增文案必须走 i18n 键表，三语齐全；扫描脚本可验证）

## 学习闭环（产品核心链路）

```text
知识资产 (EPUB/PDF/DOCX/MD/TXT/HTML/粘贴)
  → 解析 (core/parsers.py，零依赖 docx 解包)
  → 知识抽取 (core/extraction.py：LLM 多分块并行 / 确定性降级)
  → 知识模型 (KnowledgeAsset: concepts + relations + learning_path)
  → 自我学习 (core/teacher.py：TeacherModel 概念深加工 + 异常检测)
  → 教学闭环 (core/tutor.py + core/learner.py)
      对齐 → 教学(例子/图示/拆解步骤) → 答题 → 参考回答对照 → 掌握度 → 到期复习(换角度重讲)
```

## 设计理念（历轮沉淀，必须遵守）

1. **来源约束是硬规则**：概念 name/definition/evidence 必须逐字出自原文；
   `_ground_evidence` 校验 + 幻觉概念丢弃；关系只描述原文确实存在的关系；
   TeacherModel 对矛盾/未定义/逻辑断点/反常主张保持"存疑"而非假装全知。
2. **教师模型 = 系统的自我理解层**：站在学习者前面（walk ahead）——
   significance / prerequisites / misconceptions / connections / external_notes（标注来源），
   异常纳入教学优先级；学习者答题与追问（learner_signals）反哺系统认知。
3. **可视化优先（快速学习）**：知识图谱是核心入口，必须是"活"的——
   - 力导向物理模拟（斥力+弹簧+引力），节点稳定后轻微漂浮（幅度 ≤0.5，不得干扰点击）
   - 可拖拽节点（邻居弹簧跟随）、悬停高亮邻居、单击弹详情侧栏（随节点变化）、
     双击教学、搜索定位、范围切换（全部资产/当前资产）、缩放（滚轮+按钮）、内容自适应缩放
   - 当前书彩色、其他资产灰色（grey_ids），跨资产共享概念连线
   - 图例必须解释颜色语义；初始化缩放保证节点可读（≥0.85）
4. **点击必须产生更深层细节**：任何可点击节点/条目都要能展开内容
   （概念面板：定义/证据/关系邻居/教师笔记/异常/动作），禁止单层死链接。
5. **学习闭环的可视化锚点**：路径阶梯、掌握度分布条、成长趋势图、复习队列、
   指标卡——Learning Gain（ADR-010）是功能取舍标尺。
6. **间隔效应**：复习队列 `due_for_review()`（薄弱 1 天、掌握 3-6 天），
   复习课用 vary=1 换角度讲解。
7. **UI 工程规则**：
   - 视图重建（`_rebuild_all_views`）必须先清旧控件引用再构建，禁止访问已删除控件
   - QGraphicsView 等大 sizeHint 控件必须设 max 高度，防挤占主内容区
   - 布局中主内容区必须 stretch（addWidget(w, 1)），避免"标题占半屏"
   - 全局 excepthook：未捕获异常写 error.log + 弹窗，禁止静默消失
8. **多语言**：所有用户可见文本走 `t(key)`；语言切换重建 topbar/sidebar/views 并
   持久化 lang.json；模块级 `_t()` 求值的常量会导致切语言失效（用渲染时查表函数）。

8. **章节目录与主题是结构入口**：技术人员学习先看结构——知识模型页必须有
   章节目录树（章节→概念，点击定位原文）与主题聚合（按关系连通分量聚类，
   一键按学习路径顺序学整个主题）。概念必须有章节归属（SourceLocation 轻量版，
   用证据位置确定性匹配章节标题，不依赖 LLM）。
9. **多形式验证闭环**：答题（参考对照）之外，教学流程必须提供
   - 快速自测（判断正误 / 步骤排序，基于证据出题，得分记入掌握度）
   - 动手实践任务（证明/构造/伪代码/复现：生成→作答→严格评估→参考解答→记入掌握度）
10. **LLM 输出语言跟随 UI**：教学/评估/追问/自测/实践的 prompt 按当前界面语言
    追加语言指令（必须在**调用时**拼接，模块级常量拼接会在 import 时冻结语言）。
11. **LLM 长输出稳定性**：单次输出超过端点限制（如 33 概念一次自检）必须分批
    （≤12/批）；长 prompt + json_mode 在部分端点返回空——优先用普通模式 +
    容错 JSON 解析；单批失败不得丢弃已成功批次。
12. **代码强制准入 + 卡壳回退（OmniScientist 借鉴，见 docs/OmniScientist_Inspiration.md）**：
    - LLM 生成的讲解/自测/实践/评估必须通过 `core/checks.py` 的代码校验
      （结构完整、讲解非定义复制、扣住本概念、anti-template 相似度），
      失败带原因重试 1 次，仍失败显式降级——prompt 里的铁律是请求，检查才是强制；
    - 学习轨迹（`record_evaluation(meta=...)`）是唯一事实源：通道/风格/策略
      轮换全部落轨迹，卡壳检测、报告、教师模型都读它而非叙述文本；
    - 卡壳闭环：连续 3 次评估不达标 → `stuck` 标签提优先级 + `Tutor.teach`
      自动轮换讲解风格 + `incorporate_stuck_signal` 写入教师模型；
    - 生成文本中绝对化措辞必须经 `checks.temper_claims` 软化。
13. **知识解码：多模态表征生成（见 docs/Knowledge_Decoder.md）**：
    - LLM 只产出 **SceneSpec**（类型化 JSON 场景规范：nodes/edges/steps/game），
      渲染一律由确定性代码完成（`core/decoder.py`），LLM 永不直接输出 SVG/HTML；
    - SceneSpec 必须过 `decoder.check_scene` 代码准入（节点数 3-8、边引用存在、
      步骤 2-6 且引用节点存在、游戏答案为合法排列），失败带原因重试 1 次，
      仍失败降级为基于概念关系的确定性场景（结构图仍在，动画/游戏缺省）；
    - 场景内容必须源于概念定义/证据/关系（来源约束延伸到多模态）；
    - 互动游戏的得分经既有 quiz 通道记入掌握度——解码产物必须回到学习闭环，
      不做"看完就走"的展示品。

## 工程纪律

- **测试前置**：每次改进后跑 `python run_tests.py --quick`（71 用例，~9s）
  —— 分层：core(30) / data(7) / ui(22+) / llm(7，有 key 自动跑)；
  测试用演示数据临时副本，绝不污染真实数据。
- 架构分层：`expert_anything/core`（无 UI 依赖，可独立测试）/
  `expert_anything/ui`（pyside_graph + pyside_widgets）/ `main.py`（入口+视图）。
- 数据本地优先：`data/`（gitignore），`data/_demo` 为演示数据（可用 regen 脚本重建）。
- LLM 可插拔：OpenAI 兼容端点，缺 key 自动确定性降级并明确标注。

## 模块职责

- **Librarian**（解析+抽取）：parsers / extraction —— 禁止教学
- **Teacher**（自我理解+异常）：teacher.py —— 禁止修改知识库
- **Tutor**（解释/举例/迁移/评估/追问）：tutor.py —— 禁止编造原文外内容
- **Coach**（路径+复习）：learner.py adaptive_path / due_for_review
- **Reviewer**（评估+参考回答）：tutor.evaluate（reference + gap）
- **Visualizer**（图谱/图表）：graph_viz + pyside_graph / pyside_widgets

## 长期演进（见 docs/）

1. SourceLocation（页码/章节定位）→ 回答引用可溯源
2. LLM prompt 随 UI 语言（当前 LLM 输出保持中文）
3. main.py 按视图拆包（ui/views/）
4. 数据库持久化 + 向量/图检索（Hybrid Knowledge）
5. 会话内多轮对话沉淀到 TeacherModel 深度闭环
