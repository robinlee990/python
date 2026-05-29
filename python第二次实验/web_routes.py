# ============================================================
# 模块 5: Web 界面模块 (web_routes.py)
# 功能：页面路由 / 用户认证（注册/登录/登出）/ 管理员功能
# ============================================================

from functools import wraps

from flask import Blueprint, render_template, request, jsonify, session

import db
from utils import login_required

web_bp = Blueprint('web', __name__)


# ==================== 页面路由 ====================

@web_bp.route('/')
def index():
    """主页：未登录跳转登录页"""
    if 'user_id' not in session:
        return render_template('index.html', logged_in=False)
    user = db.get_user_by_id(session['user_id'])
    return render_template('index.html', logged_in=True, user=user)


@web_bp.route('/login')
def login_page():
    return render_template('index.html', logged_in=False)


# ==================== 用户认证 API ====================

@web_bp.route('/api/auth/register', methods=['POST'])
def api_register():
    """注册"""
    data = request.get_json() or {}
    username = (data.get('username', '')).strip()
    password = (data.get('password', '')).strip()
    nickname = (data.get('nickname', '')).strip()

    if len(username) < 3:
        return jsonify({"error": "用户名至少 3 位"}), 400
    if len(password) < 6:
        return jsonify({"error": "密码至少 6 位"}), 400

    ok, msg = db.create_user(username, password, nickname)
    if ok:
        return jsonify({"message": msg})
    return jsonify({"error": msg}), 400


@web_bp.route('/api/auth/login', methods=['POST'])
def api_login():
    """登录"""
    data = request.get_json() or {}
    username = (data.get('username', '')).strip()
    password = (data.get('password', '')).strip()

    user = db.verify_user(username, password)
    if user:
        session.permanent = True
        session['user_id'] = user['id']
        session['username'] = user['username']
        return jsonify({
            "message": "登录成功",
            "user": {"id": user['id'], "username": user['username'],
                     "nickname": user['nickname'], "role": user['role']}
        })
    return jsonify({"error": "用户名或密码错误"}), 401


@web_bp.route('/api/auth/logout', methods=['POST'])
def api_logout():
    """退出登录"""
    session.clear()
    return jsonify({"message": "已退出"})


@web_bp.route('/api/auth/me', methods=['GET'])
@login_required
def api_me():
    """获取当前用户信息"""
    user = db.get_user_by_id(session['user_id'])
    return jsonify({"user": user})


# ==================== 管理员 API ====================

@web_bp.route('/api/admin/users', methods=['GET'])
@login_required
def admin_list_users():
    user = db.get_user_by_id(session['user_id'])
    if user['role'] != 'admin':
        return jsonify({"error": "无权限"}), 403
    return jsonify({"users": db.get_all_users()})


@web_bp.route('/api/admin/files', methods=['GET'])
@login_required
def admin_list_files():
    user = db.get_user_by_id(session['user_id'])
    if user['role'] != 'admin':
        return jsonify({"error": "无权限"}), 403
    return jsonify({"files": db.get_all_files()})

# ==================== 管理员检索 API ====================

def _admin_required(f):
    """装饰器：要求管理员权限"""
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        user = db.get_user_by_id(session['user_id'])
        if not user or user['role'] != 'admin':
            return jsonify({"error": "无权限，仅管理员可访问"}), 403
        return f(*args, **kwargs)
    return wrapper


@web_bp.route('/api/admin/stats', methods=['GET'])
@_admin_required
def admin_stats():
    """管理员全局统计概览"""
    return jsonify(db.get_admin_stats())


@web_bp.route('/api/admin/search/users', methods=['GET'])
@_admin_required
def admin_search_users():
    """
    检索用户
    Query 参数：
      keyword   - 用户名/昵称关键字（模糊匹配）
      role      - 角色筛选（user / admin）
      date_from - 注册时间起（YYYY-MM-DD）
      date_to   - 注册时间止（YYYY-MM-DD）
      page      - 页码（默认 1）
      per_page  - 每页条数（默认 20，最大 100）
    """
    keyword   = request.args.get('keyword', '')
    role      = request.args.get('role', '')
    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')
    page      = request.args.get('page', 1, type=int)
    per_page  = min(request.args.get('per_page', 20, type=int), 100)

    result = db.search_users(
        keyword=keyword, role=role,
        date_from=date_from, date_to=date_to,
        page=page, per_page=per_page,
    )
    return jsonify(result)


@web_bp.route('/api/admin/search/files', methods=['GET'])
@_admin_required
def admin_search_files():
    """
    检索文件
    Query 参数：
      keyword   - 文件名关键字（模糊匹配）
      username  - 上传用户名（模糊匹配）
      status    - 状态筛选（uploaded / cleaned）
      date_from - 上传时间起（YYYY-MM-DD）
      date_to   - 上传时间止（YYYY-MM-DD）
      min_rows  - 最小行数
      max_rows  - 最大行数
      page      - 页码（默认 1）
      per_page  - 每页条数（默认 20，最大 100）
    """
    keyword   = request.args.get('keyword', '')
    username  = request.args.get('username', '')
    status    = request.args.get('status', '')
    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')
    min_rows  = request.args.get('min_rows', None, type=int)
    max_rows  = request.args.get('max_rows', None, type=int)
    page      = request.args.get('page', 1, type=int)
    per_page  = min(request.args.get('per_page', 20, type=int), 100)

    result = db.search_files(
        keyword=keyword, username=username, status=status,
        date_from=date_from, date_to=date_to,
        min_rows=min_rows, max_rows=max_rows,
        page=page, per_page=per_page,
    )
    return jsonify(result)


@web_bp.route('/api/admin/search/cleaning-logs', methods=['GET'])
@_admin_required
def admin_search_cleaning_logs():
    """
    检索清洗日志
    Query 参数：
      keyword   - 文件名关键字（模糊匹配）
      username  - 操作用户名（模糊匹配）
      date_from - 操作时间起（YYYY-MM-DD）
      date_to   - 操作时间止（YYYY-MM-DD）
      page      - 页码（默认 1）
      per_page  - 每页条数（默认 20，最大 100）
    """
    keyword   = request.args.get('keyword', '')
    username  = request.args.get('username', '')
    date_from = request.args.get('date_from', '')
    date_to   = request.args.get('date_to', '')
    page      = request.args.get('page', 1, type=int)
    per_page  = min(request.args.get('per_page', 20, type=int), 100)

    result = db.search_cleaning_logs(
        keyword=keyword, username=username,
        date_from=date_from, date_to=date_to,
        page=page, per_page=per_page,
    )
    return jsonify(result)


@web_bp.route('/api/admin/search/analysis-results', methods=['GET'])
@_admin_required
def admin_search_analysis_results():
    """
    检索分析记录
    Query 参数：
      keyword       - 文件名关键字（模糊匹配）
      username      - 操作用户名（模糊匹配）
      analysis_type - 分析类型筛选（clustering / regression / pca）
      date_from     - 分析时间起（YYYY-MM-DD）
      date_to       - 分析时间止（YYYY-MM-DD）
      page          - 页码（默认 1）
      per_page      - 每页条数（默认 20，最大 100）
    """
    keyword       = request.args.get('keyword', '')
    username      = request.args.get('username', '')
    analysis_type = request.args.get('analysis_type', '')
    date_from     = request.args.get('date_from', '')
    date_to       = request.args.get('date_to', '')
    page          = request.args.get('page', 1, type=int)
    per_page      = min(request.args.get('per_page', 20, type=int), 100)

    result = db.search_analysis_results(
        keyword=keyword, username=username,
        analysis_type=analysis_type,
        date_from=date_from, date_to=date_to,
        page=page, per_page=per_page,
    )
    return jsonify(result)