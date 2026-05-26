# ============================================================
# 主入口: app.py
# 交互式数据分析系统 —— 模块化架构（5 人协作版本）
#
# 模块分工：
#   utils.py        → 共享工具（装饰器 + 辅助函数）
#   db.py           → 数据库层（MySQL 持久化）
#   data_manager.py → 模块1: 数据管理（上传/预览/导出/统计）
#   data_cleaner.py → 模块2: 数据清洗（缺失值/异常值/去重）
#   visualizer.py   → 模块3: 可视化（8 种图表动态生成）
#   analyzer.py     → 模块4: 分析功能（聚类/回归/PCA）
#   web_routes.py   → 模块5: Web 界面（认证/页面路由/管理员）
# ============================================================

import os

from flask import Flask

import db
from data_manager import data_bp
from data_cleaner import clean_bp
from visualizer import viz_bp
from analyzer import analyze_bp
from web_routes import web_bp

# ---- Flask 配置 ----
app = Flask(__name__)
app.secret_key = 'data-analysis-system-db-2024-secret-key'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# ---- 注册蓝图（5 个模块） ----
app.register_blueprint(web_bp)        # 模块5: Web 界面（页面 + 认证）
app.register_blueprint(data_bp)       # 模块1: 数据管理
app.register_blueprint(clean_bp)      # 模块2: 数据清洗
app.register_blueprint(viz_bp)        # 模块3: 可视化
app.register_blueprint(analyze_bp)    # 模块4: 分析功能

# ---- 启动 ----
if __name__ == '__main__':
    print("=" * 60)
    print("  交互式数据分析系统 - 模块化架构 v2.0")
    print("  访问地址: http://127.0.0.1:5000")
    print("  默认管理员: admin / admin123")
    print("")
    print("  模块分工：")
    print("    模块1 数据管理 → data_manager.py")
    print("    模块2 数据清洗 → data_cleaner.py")
    print("    模块3 可视化   → visualizer.py")
    print("    模块4 分析功能 → analyzer.py")
    print("    模块5 Web界面  → web_routes.py")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=5000)
