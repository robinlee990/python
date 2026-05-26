# ============================================================
# 模块 0: 共享工具函数和装饰器
# 供所有模块共同使用
# ============================================================

import json
from functools import wraps
from flask import session, jsonify

import db


def login_required(f):
    """装饰器：要求用户已登录"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "请先登录"}), 401
        return f(*args, **kwargs)
    return wrapper


def require_file(f):
    """装饰器：要求已选择文件（从数据库加载）"""
    @wraps(f)
    @login_required
    def wrapper(*args, **kwargs):
        file_id = session.get('file_id')
        if not file_id:
            return jsonify({"error": "请先选择数据文件"}), 400
        return f(*args, **kwargs)
    return wrapper


def df_to_json(df, orient='records'):
    """DataFrame → JSON"""
    return json.loads(df.fillna("").to_json(orient=orient, force_ascii=False))


def analyze_columns(df):
    """分析列信息"""
    columns_info = []
    for col in df.columns:
        dtype = str(df[col].dtype)
        missing = int(df[col].isna().sum())
        unique = int(df[col].nunique())
        if 'int' in dtype or 'float' in dtype:
            col_type = 'numeric'
        elif 'datetime' in dtype:
            col_type = 'datetime'
        else:
            col_type = 'categorical'
        columns_info.append({
            "name": col,
            "dtype": dtype,
            "type": col_type,
            "missing": missing,
            "unique": unique,
            "recommended_charts": ['histogram', 'box'] if col_type == 'numeric' else ['bar', 'pie'],
        })
    return columns_info


def load_active_df():
    """从数据库加载当前选定文件的数据为 DataFrame"""
    file_id = session.get('file_id')
    if not file_id:
        return None, None, None
    df, cols = db.get_data_as_df(file_id)
    file_info = db.get_file_by_id(file_id)
    return df, cols, file_info
