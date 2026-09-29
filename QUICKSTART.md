---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: f72b104002d99af940831fcb029a9bd5_79aab908b6bd11f18c29525400de85a5
    ReservedCode1: iFah8YUanGn/zdi1anNWqK/2JrKklyc4vJiJbx87dyfJ/W1DR8aG/zeXBp9DEQWVTAvwTwFvMmkQDlMDcEya97dYGKb+lCAUrEcEhtP2O/AOfDgSxb0dURTqx/GVMSE2FLuqHSaR9oDFNWingZPGOSQ9zgL/c1x7w/YfG8hTGc3WbWgNx50m2iCvoYA=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: f72b104002d99af940831fcb029a9bd5_79aab908b6bd11f18c29525400de85a5
    ReservedCode2: iFah8YUanGn/zdi1anNWqK/2JrKklyc4vJiJbx87dyfJ/W1DR8aG/zeXBp9DEQWVTAvwTwFvMmkQDlMDcEya97dYGKb+lCAUrEcEhtP2O/AOfDgSxb0dURTqx/GVMSE2FLuqHSaR9oDFNWingZPGOSQ9zgL/c1x7w/YfG8hTGc3WbWgNx50m2iCvoYA=
---

# ExpertAnything 快速启动指南

## 方式一：直接启动（推荐）

```bash
# Windows
start-electricity-demo.bat

# macOS/Linux
chmod +x start-electricity-demo.sh
./start-electricity-demo.sh

# 通用
python main.py
```

## 方式二：从导入界面套用领域模板（已实现）

无需手动挑选选项：导入流程会在抽取完成后**自动检测领域并弹出确认框**。

1. 启动应用后，点击左侧导航栏 **"📥 导入知识资产"**
2. 选择本地资料（如 `data/_demo/electricity_trading_asset.json`），等待抽取完成
3. 若资料标题命中已注册领域（当前为 `electricity_trading`）且模板概念覆盖率达标，
   界面会弹出 **"领域模板"** 确认框，文案形如：
   > 检测到本资料可套用领域模板《中国电力市场交易体系》：命中 10/19 个模板概念（覆盖率 53%）。
   > 套用后将为命中的概念补充模板释义，并可能把学习路径更新为领域推荐顺序。是否套用？
4. 点 **"是"** 才套用：命中的概念按需补 `definition`（仅在原本为空时），学习路径可能被改写为
   模板推荐顺序；点 **"否"**、标题未命中领域、或覆盖率低于 50% 时**按原流程导入，原学习路径保持不变**
5. 进入 **"🗺️ 认知地图"** 与概念详情侧栏，查看领域专用可视化场景（市场架构 / 电价形成 / 交易流程 / LMP）

> 说明：抽取步骤需要 LLM API Key，或在设置中切换到确定性模式；未安装 `PySide6` 时无 GUI 可用，请改用方式一或方式三。

## 方式三：命令行加载演示数据

```bash
python -c "
from expert_anything.core.domain_templates import detect_domain_from_title, apply_domain_template
from expert_anything.core.models import KnowledgeAsset
from pathlib import Path
import json

# 加载演示资产
asset = KnowledgeAsset.from_dict(json.loads(
    Path('data/_demo/electricity_trading_asset.json').read_text(encoding='utf-8')
))

# 检测领域
domain = detect_domain_from_title(asset.title)
print(f'检测到领域: {domain}')

# 应用模板（返回 TemplateApplicationResult，可用于展示映射统计）
result = apply_domain_template(asset, domain)
print(f'应用结果: {result.reason}，覆盖率 {result.coverage:.0%}，'
      f'命中 {result.matched_count}/{result.template_concept_count} 个概念，'
      f'富化 {result.enriched_count} 个概念')
if result.degraded:
    print('原学习路径保持不变（映射为空或覆盖率过低）')
print(f'已应用模板，概念数: {len(asset.concepts)}')
print(f'学习路径: {asset.learning_path}')
"
```

> 实测输出（2026-09-22）：`domain: electricity_trading`、`reason: ok`、`cov: 0.526`、`10 / 19`、
> `enriched: 0`、`degraded: False`、`path: ['c001', 'c005', 'c007', 'c008']`。
>
> 注意：`data/` 已被 `.gitignore` 排除，`data/_demo/electricity_trading_asset.json` 需本机自备
> （或参考 `run_demo.py` 内联构造的演示资产）；该片段只在内存中套用模板，不会回写文件。

## 核心功能验证

### 测试领域模板
```bash
python -m unittest tests.test_domain_templates -v   # 43 例：映射 / 别名 / 降级 / 套用
python run_tests.py --layer core                    # core 层全量（含上述用例）
```

### 运行完整测试套件
```bash
python run_tests.py --quick   # 跳过 LLM 层，约 10 秒
python run_tests.py           # 全量（无 API Key 时 LLM 层自动 skip）
```

### 一键跑通领域演示
```bash
python run_demo.py   # 套用模板 → 生成 4 个场景并校验 → 输出 demo_electricity_market.html
```

### 生成互动演示页面
```bash
python -c "
from expert_anything.core.decoder_electricity import generate_market_architecture_scene
from expert_anything.core.decoder import render_interactive_html

scene = generate_market_architecture_scene()
# 真实签名: render_interactive_html(spec, concept='', source_title='', definition='', evidence=None)
html = render_interactive_html(scene, concept='两级市场架构', source_title='中国电力市场')
print('HTML演示页面已生成')
print(html[:500] + '...')  # 显示前500字符
"
```

## 主要视图说明

| 视图 | 功能 | 导航入口（界面文案） |
|------|------|--------|
| **导入知识资产** | 导入本地资料、抽取概念，抽取后询问是否套用领域模板 | 📥 导入知识资产 |
| **认知地图**（概念网络图） | 力导向图，可视化所有概念关系 | 🗺️ 认知地图（默认首页） |
| **知识模型** | 仪表盘、章节结构、主题聚类 | 🌳 知识模型 |
| **教学会话** | 多风格讲解（例子/图示/拆解步骤） | 🎓 教学会话 |
| **阅读原文** | 原始文本与高亮概念对应 | 📖 阅读原文 |
| **学习者模型** | 掌握度追踪与趋势图 | 🧠 学习者模型 |
| **教师模型** | 异常检测与深度学习笔记 | 👨‍🏫 教师模型 |

## 键盘快捷键

当前版本**未实现全局快捷键**，视图切换请使用左侧导航栏；教学会话中的步骤切换与动画播放使用界面按钮。

## 依赖安装

```bash
# 基础依赖
pip install -r requirements.txt

# 可选：测试依赖
pip install pytest pytest-cov
```

## 常见问题

**Q: 启动后出现白色窗口或黑屏？**
A: 尝试设置环境变量 `QT_GRAPHICSSYSTEM=raster`

**Q: 概念图不显示？**
A: 确保至少有一个已导入的知识资产，检查 `data/assets/*.json`

**Q: 教学会话无响应？**
A: 需要配置 LLM API Key，或在设置中选择"确定性模式"

**Q: 测试失败？**
A: 先运行 `python run_tests.py --quick` 定位。
- 若 `tests/test_core.py::test_pdf_extraction` 失败（断言 `PDF text content not found in ''`），
  原因是本机缺少 `pypdf`（`requirements.txt` 已声明 `pypdf>=4.0`），缺失时 PDF 解析器返回空文本。
  执行 `pip install -r requirements.txt` 后该用例即通过。
- `ui` 层用例需要 `PySide6`、`llm` 层需要 LLM API Key，缺失时 runner 会整层 skip 并在摘要中显示
  （如 `OK (skipped=7)`），skip 不等于通过。

## 下一步

1. 加载电力交易演示资产
2. 学习"两级市场架构"概念
3. 尝试不同教学风格（例子/图示/拆解步骤）
4. 完成自测题目，提升掌握度
5. 探索领域模板在其他场景的应用
*（内容由AI生成，仅供参考）*
