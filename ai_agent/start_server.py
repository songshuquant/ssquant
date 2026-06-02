# -*- coding: utf-8 -*-
"""
SSQuant AI Agent - 生产级服务器启动脚本
使用 waitress 替代 Flask 开发服务器，根治长时间运行/后台切换问题

用法:
    cd ai_agent
    python start_server.py
"""

import sys
import os

# 确保在项目根目录
cwd = os.path.dirname(os.path.abspath(__file__))
os.chdir(cwd)

# 将项目根目录加入 Python 路径（解决模块导入问题）
project_root = os.path.dirname(cwd)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

print("=" * 60)
print(">>> SSQuant AI Agent 生产模式启动中...")
print("=" * 60)
print(f"工作目录: {cwd}")
print(f"Python: {sys.executable}")
print("=" * 60)
print("\n访问地址: http://localhost:5000")
print("按 Ctrl+C 停止服务\n")

try:
    from waitress import serve
    from backend import app
    
    # waitress 生产级配置
    # threads: 线程数，8 个足够处理 SSE 长连接 + API 请求
    # channel_timeout: 连接超时，300 秒匹配后端 API 超时
    # cleanup_interval: 清理间隔
    serve(
        app,
        host='0.0.0.0',
        port=5000,
        threads=8,
        channel_timeout=300,
        cleanup_interval=30,
        expose_tracebacks=False  # 生产环境不暴露堆栈
    )
except ImportError:
    print("\n[错误] waitress 未安装，请先执行:")
    print("    pip install waitress")
    sys.exit(1)
except KeyboardInterrupt:
    print("\n>>> 服务已停止")
