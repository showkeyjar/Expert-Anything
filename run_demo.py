"""电力交易领域演示脚本 - 无需GUI即可验证所有功能"""
import sys
import json
from pathlib import Path

# 切换到项目目录
sys.path.insert(0, str(Path(__file__).parent))

def main():
    print("=" * 60)
    print("  ExpertAnything 电力交易领域演示")
    print("=" * 60)
    print()

    # 1. 加载演示资产
    print("1. 加载电力交易演示资产...")
    asset_path = Path("data/_demo/electricity_trading_asset.json")
    if not asset_path.exists():
        print(f"   ✗ 找不到演示文件: {asset_path}")
        return 1
    
    with open(asset_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    from expert_anything.core.models import KnowledgeAsset
    asset = KnowledgeAsset.from_dict(data)
    print(f"   ✓ 资产标题: {asset.title}")
    print(f"   ✓ 概念数量: {len(asset.concepts)}")
    print(f"   ✓ 关系数量: {len(asset.relations)}")
    print(f"   ✓ 学习路径长度: {len(asset.learning_path)}")
    print()

    # 2. 应用领域模板
    print("2. 应用电力交易领域模板...")
    from expert_anything.core.domain_templates import (
        detect_domain_from_title,
        apply_domain_template,
    )
    
    domain = detect_domain_from_title(asset.title)
    print(f"   检测领域: {domain}")
    
    if domain:
        result = apply_domain_template(asset, domain)
        print(f"   ✓ 模板应用结果: {result}")
        print(f"   ✓ 快速路径: {asset.learning_path[:5]}...")
    print()

    # 3. 生成场景
    print("3. 生成可视化场景...")
    from expert_anything.core.decoder_electricity import (
        generate_market_architecture_scene,
        generate_price_formation_scene,
        generate_trading_process_scene,
        generate_lmp_scene,
        get_scene_for_concept,
    )
    
    scenes = [
        ("市场架构", generate_market_architecture_scene),
        ("电价形成", generate_price_formation_scene),
        ("交易流程", generate_trading_process_scene),
        ("LMP电价", generate_lmp_scene),
    ]
    
    for name, generator in scenes:
        scene = generator()
        if scene:
            nodes = len(scene.get("nodes", []))
            edges = len(scene.get("edges", []))
            steps = len(scene.get("steps", []))
            has_game = "有游戏" if scene.get("game") else "无游戏"
            print(f"   ✓ {name}: {nodes}节点/{edges}边/{steps}步/{has_game}")
        else:
            print(f"   ✗ {name}: 生成失败")
    print()

    # 4. 验证场景
    print("4. 验证场景合法性...")
    from expert_anything.core.decoder import check_scene
    
    all_scenes = [s() for _, s in scenes]
    valid_count = 0
    for i, scene in enumerate(all_scenes):
        if scene:
            verdict, _ = check_scene(scene)
            if verdict:
                valid_count += 1
                print(f"   ✓ 场景 {i+1}: 通过验证")
            else:
                print(f"   ✗ 场景 {i+1}: 验证失败")
    
    print(f"   验证结果: {valid_count}/{len(all_scenes)} 通过")
    print()

    # 5. 测试概念映射（三种解析方式：模板ID / 资产ID / 概念名称）
    print("5. 测试概念-场景映射（模板ID / 资产ID / 概念名称）...")
    concept_scenes = [
        ("et-001", "模板ID", "市场架构"),
        ("c001", "资产ID", "市场架构"),
        ("两级市场架构", "概念名称", "市场架构"),
        ("et-010", "模板ID", "电价机制"),
        ("c007", "资产ID", "电价机制"),
        ("输配电价", "概念名称", "电价机制"),
        ("et-015", "模板ID", "交易流程"),
        ("et-013", "模板ID", "LMP定价"),
        ("c008", "资产ID", "LMP定价"),
        ("节点边际电价(LMP)", "别名", "LMP定价"),
        ("LMP", "括号别名", "LMP定价"),
        ("现货交易", "无专用场景", "（应回退通用场景）"),
    ]

    for ref, route, expected_name in concept_scenes:
        scene = get_scene_for_concept(ref, asset)
        if scene:
            print(f"   ✓ [{route}] {ref}: {scene['title']}")
        else:
            print(f"   - [{route}] {ref}: 无专用场景（回退通用 decoder）")
    print()

    # 6. 生成交互式HTML演示
    print("6. 生成交互式HTML演示...")
    from expert_anything.core.decoder import render_interactive_html
    
    scene = generate_market_architecture_scene()
    if scene:
        html_path = Path("demo_electricity_market.html")
        html = render_interactive_html(
            scene,
            concept="两级市场架构",
            source_title=asset.title
        )
        html_path.write_text(html, encoding="utf-8")
        print(f"   ✓ HTML已生成: {html_path.absolute()}")
        print(f"   ✓ 文件大小: {html_path.stat().st_size} 字节")
        print()
        print("   双击以下文件可在浏览器中打开:")
        print(f"   {html_path.absolute()}")
    else:
        print("   ✗ HTML生成失败")
    
    print()
    print("=" * 60)
    print("  演示完成！")
    print("=" * 60)
    print()
    print("下一步：")
    print("  1. 运行 python main.py 启动桌面应用")
    print("  2. 在导入视图选择'使用领域模板'")
    print("  3. 查看概念网络视图中的可视化场景")
    print()
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
