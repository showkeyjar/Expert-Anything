# ExpertAnything · 个人学习 OS

> Make anyone expert in anything.

把任何知识资产（书、论文、课程、笔记）转化为**可交互、可教学、可进化的知识模型**，通过「学习闭环」帮人真正掌握，而不是做一个 RAG 聊天机器人。

## 运行

```powershell
pip install -r requirements.txt
python app.py        # 或 python main.py
```

PySide6 桌面应用，无需浏览器。首次使用建议在 `.env` 中配置 LLM（见 `.env.example`）：

```
EXPERTANYTHING_LLM_API_KEY=...
EXPERTANYTHING_LLM_BASE_URL=https://api.openai.com/v1   # 任意 OpenAI 兼容端点
EXPERTANYTHING_LLM_MODEL=gpt-4o-mini
```

未配置 LLM 时系统以「确定性降级」运行：抽取概念结构索引、教学与评估退化为启发式，UI 会明确提示深度受限。

## 核心链路

```text
知识资产 (EPUB/PDF/MD/TXT/粘贴文本)
  -> 格式解析 (core/parsers.py)
  -> 知识抽取 (core/extraction.py)   ← LLM 多分块并行，来源约束，幻觉防护
  -> 知识模型 (KnowledgeAsset: concepts + relations + learning_path)
  -> 自我学习 (core/teacher.py)      ← 概念深加工 + 异常检测 (TeacherModel)
  -> 教学闭环 (core/tutor.py + core/learner.py)
      对齐目标 → 教学(例子/图示/拆解) → 答题评估 → 更新掌握度 → 自适应下一步
```

**来源约束是硬规则**：概念的 definition/evidence 必须逐字出自原文，关系只标原文存在的联系；`TeacherModel` 对原文的矛盾、未定义术语、逻辑断点、反常主张保持「存疑」而非假装全知，并把异常纳入教学优先级（walk ahead of the student）。

## 目录结构

```text
app.py / main.py            PySide6 桌面入口（7 个视图）
expert_anything/
  core/                     核心引擎（无 UI 依赖，可单独测试）
    extraction.py           知识抽取（LLM + 确定性回退）
    teacher.py              自我学习层（ConceptNote + Anomaly + 学习者信号闭环）
    tutor.py                个性化教学（3 种风格 + 语义评估）
    learner.py              跨资产掌握度 + 自适应学习路径
    llm.py                  零依赖 OpenAI 兼容客户端（重试/退避/并发限流）
    graph_viz.py            Pillow 离线概念图渲染 + 布局算法
    i18n.py                 中/英双语
    models.py / storage.py / parsers.py / config.py
  ui/
    pyside_graph.py         PySide6 交互式知识图谱（复用 graph_viz 布局）
    app.py / concept_cards.py / graph_widget.py   ← 已退役的 Flet 版，仅参考
data/                       运行时数据（learner.json + assets/，不入库）
docs/                       设计理念 / ADR / 来源约束架构
legacy/                     Web 版与 PySide6 v1 存档
verify_core.py / verify_teacher.py   无头验证（核心闭环 / 教师模型，含真实 LLM）
```

## 桌面端 7 个视图

1. **导入知识资产** — 文件（EPUB/PDF/MD/TXT）或粘贴文本，后台线程抽取 + 自我学习，实时进度
2. **知识模型** — 仪表盘 + 自适应学习路径（掌握度/异常/基础杠杆/路径位置四信号排序）
3. **概念网络图** — 交互式图谱：单击节点聚焦其知识网络（径向重排），双击开始学习，滚轮缩放、拖拽平移；掌握度四档配色、异常橙色描边、推荐项蓝色描边
4. **阅读原文** — 查看资产原文
5. **教学会话** — 对齐目标 → 按偏好风格（例子/图示/拆解步骤）生成讲解 → 答题 → 语义评估 → 更新 Learner Model
6. **学习者模型** — 跨资产掌握度排行、薄弱项、最近 50 条学习历史、导出学习报告
7. **教师模型** — 系统自我理解（概念笔记 + 异常列表），可重新自检

## 验证

```powershell
python verify_core.py      # 核心学习闭环（无 LLM）
python verify_teacher.py   # 教师模型 + 真实 LLM 路径（需配置 key）
```

## 后续演进（见 docs/）

1. 抽取层抽象为 `KnowledgeExtractor` 接口（LLM / PDF 专用解析器）
2. 引入 `SourceLocation`（页码/章节/段落）并升级结构化抽取
3. 持久化升级为数据库；接入向量检索 + 图数据库（Hybrid Knowledge）
4. 学习路径从线性列表升级为基于前置关系与 Learner Model 的 Coach Agent
5. PySide6 单文件 `main.py` 按视图拆分为包（`ui/views/`）
