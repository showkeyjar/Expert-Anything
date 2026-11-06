# Knowledge Decoder — 知识解码与生成系统架构

> 愿景（用户，2026-08-18）：本系统不仅是一个辅助学习系统，更是一个**知识解码和生成系统**——
> 应能把抽象的知识"解译"成图像、动画、视频、互动游戏，**直到用户完全理解**。

## 1. 定位

学习闭环回答"教什么、何时教、教得怎样"；知识解码回答"**用什么形态教**"。
同一条概念证据，对不同学习者、不同掌握阶段，最优表征形态不同：
结构图（看关系）→ 分步动画（看过程）→ 互动游戏（亲手操作）→ 直到完全理解。

## 2. 核心管线（开放推理 + 确定性外壳，延续 OmniScientist 借鉴）

```text
概念 + 定义 + 原文证据 + 关系网络
  → LLM 产出 SceneSpec（类型化 JSON 场景规范）        ← 开放推理：只描述"场景里有什么"
  → decoder.check_scene() 代码准入校验                ← 确定性外壳：结构合法性强制
      （节点 3-8、id 唯一、边/步骤引用存在、步骤 2-6 且有 caption、
        游戏答案为 0..n-1 排列；失败带原因重试 1 次）
  → 确定性渲染器（core/decoder.py，纯标准库）          ← LLM 永不直接输出 SVG/HTML
      render_svg(spec, step)        静态/单步结构图
      render_step_svgs(spec)        分步动画帧序列
      render_interactive_html(spec) 自包含 HTML（动画 + 排序小游戏）
  → 学习闭环回写
      桌面端：DecoderSceneCard（QtSvg 分步播放器 + 应用内排序游戏）
      游戏得分 → quiz_result 信号 → record_evaluation → 掌握度
      浏览器：临时 HTML（QDesktopServices 打开，离线自包含，无 CDN）
```

**铁律（来源约束延伸到多模态）**：场景节点与步骤必须源于概念的
定义/证据/关系；LLM 编造的实体无法通过证据锚定，由 prompt 约束 +
check_scene 结构校验双层把关（SourceLocation 已落地，证据级锚定与
原文双向跳转见 AGENTS.md 设计理念 §4）。

## 2.1 逐级递增原则（progressive representation）

知识的生动表示是**逐级递增**的，目的是用最小的认知代价让用户理解，
而不是一上来就互动：

| 级 | 表征 | 何时出现 |
|---|---|---|
| L1 | 静态全景结构图 | 默认视图，一屏看清整体 |
| L2 | 分步讲解动画 | 用户主动点击（分步讲解 / → / 空格）才进入 |
| L3 | 互动游戏 | 页面下方独立区块，永远不会自动弹出 |

HTML 演示页与桌面卡片都遵守：初始即 L1 全景，可随时"返回全景"；
动画永不默认播放。

## 2.2 布局确定性（layout is presentation）

**LLM 不提供坐标**（prompt 已明确禁止）；坐标完全由 `_layout()` 决定：

- 最长路径分层：源在左、汇在右（≤4 层时横向流水线）
- 长链（>4 层）自动转纵向自上而下排布，节点尺寸不缩水
- 节点高度随标签行数自适应；**零重叠由构造保证**（列独占 x 段，
  行内独占 y 段），有对抗性测试兜底（test_layout_never_overlaps）

## 3. SceneSpec 规范

```json
{
  "title": "场景标题（15字内）",
  "nodes": [ {"id": "n1", "label": "节点名", "kind": "box|store|flow|note|current"} ],   // 3-8 个
  "edges": [ {"from": "n1", "to": "n2", "label": "关系", "dashed": false} ],
  "steps": [ {"caption": "这一步发生了什么", "show": ["n1","n2"], "active": "n1"} ],     // 2-6 步，show 累计可见
  "game":   {"type": "sort", "goal": "…", "items": ["乱序条目"], "answer": [2,0,1]}      // 可选
}
```

- **禁止提供坐标**：布局由 `_layout()` 确定性完成（见 2.2），LLM 给的 x/y 一律忽略
- `kind` 决定配色语义：box=概念 / store=存储 / flow=动作 / note=说明 / current=当前概念（深蓝高亮）
- `game.answer` 容错后必须是 items 索引的一个排列——与自测 ordering 题同一套校验思想

## 4. 降级阶梯（任何一级失败都有下一级）

1. LLM SceneSpec 通过校验 → 完整体验（动画 + 游戏 + HTML 演示）
2. LLM 规范两次失败 → `decoder.fallback_scene()`：由概念关系图确定性生成场景
   （当前概念居中 current、邻居按关系连线、逐步揭示），动画可用、游戏缺省
3. 无 LLM 环境 → 直接走 2（演示模式下知识解译依然可用）

## 5. 路线图

| 表征形态 | 状态 | 说明 |
|---|---|---|
| 静态结构图（SVG） | ✅ 已落地 | render_svg，来源约束场景 |
| 分步动画（帧序列） | ✅ 已落地 | 桌面 QtSvg 播放器 + HTML 自动播放 |
| 互动排序游戏 | ✅ 已落地 | 应用内（得分回写掌握度）+ 浏览器 HTML |
| 浏览器互动演示页 | ✅ 已落地 | 自包含离线 HTML，无外部依赖 |
| 匹配/连线游戏 (match) | ⏳ 候选 | items→buckets，校验答案为合法分配 |
| 模拟/操作式游戏 (simulation) | ⏳ 候选 | 学习者直接操纵场景参数观察因果（如调 u* 阈值看通量变化） |
| 视频表征 | ⏳ 候选 | 帧序列 + 字幕 → ffmpeg 合成；复用 SceneSpec 步骤为分镜脚本 |
| 感知层预算 | ⏳ 候选 | 何时值得为这个概念生成这种形态（掌握度 × 卡壳信号 × 形态成本） |

## 6. 关联文档

- `AGENTS.md` 设计理念第 13 条（知识解码铁律）
- `docs/OmniScientist_Inspiration.md`（开放推理+确定性外壳的来源）
- `expert_anything/core/decoder.py` / `expert_anything/ui/pyside_widgets.py::DecoderSceneCard`
