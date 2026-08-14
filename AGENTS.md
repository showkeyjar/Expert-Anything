# AGENTS.md

# Project: ExpertAnything — Personal Learning OS

## Vision
> Make anyone expert in anything.

The system transforms books, papers, documents and courses into interactive,
adaptive learning experiences. It is **not an AI reader** — it is a Knowledge
Runtime: 知识资产 → 知识模型 → 学习闭环 → 能力成长.

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
