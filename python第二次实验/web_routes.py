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
