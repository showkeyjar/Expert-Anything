#!/bin/bash

# ExpertAnything - 电力交易领域演示启动脚本

echo ""
echo "=========================================="
echo "  ExpertAnything 电力交易领域演示系统"
echo "=========================================="
echo ""
echo "即将启动桌面应用，演示场景："
echo "  - 市场架构可视化"
echo "  - 电价形成机制"
echo "  - 日前市场交易流程"
echo "  - LMP节点边际电价"
echo ""

# 切换到项目目录
cd "$(dirname "$0")"

# 启动应用
python3 main.py || python main.py

exit $?
