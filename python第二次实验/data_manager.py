# ============================================================
# 模块 1: 数据管理模块 (data_manager.py)
# 功能：文件上传 / 预览 / 查看 / 删除 / 重置 / 统计 / 导出
# ============================================================

import os
import io
import json
import base64
from datetime import datetime

import pandas as pd
from flask import Blueprint, request, jsonify, session, send_file
from werkzeug.utils import secure_filename

import db
from utils import login_required, require_file, analyze_columns, load_active_df

data_bp = Blueprint('data', __name__, url_prefix='/api')


# ==================== 文件上传 ====================

@data_bp.route('/upload', methods=['POST'])
@login_required
def upload_file():
    """上传 CSV/Excel 文件并存入数据库"""
    from flask import current_app

    if 'file' not in request.files:
        return jsonify({"error": "未找到文件"}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "未选择文件"}), 400

    original_name = file.filename
    filename = secure_filename(original_name)
    ext = os.path.splitext(filename)[1].lower()

    # 解析文件
    try:
        file_data = file.read()
        if ext == '.csv':
            for encoding in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
                try:
                    df = pd.read_csv(io.BytesIO(file_data), encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                df = pd.read_csv(io.BytesIO(file_data), encoding='utf-8', errors='ignore')
        elif ext in ['.xlsx', '.xls']:
            df = pd.read_excel(io.BytesIO(file_data))
        else:
            return jsonify({"error": f"不支持的文件格式: {ext}"}), 400
    except Exception as e:
        return jsonify({"error": f"文件解析失败: {str(e)}"}), 400

    # 保存原始文件到磁盘
    upload_folder = current_app.config['UPLOAD_FOLDER']
    saved_path = os.path.join(
        upload_folder,
        f"{session['user_id']}_{datetime.now().strftime('%Y%m%d%H%M%S')}_{filename}"
    )
    with open(saved_path, 'wb') as f:
        f.write(file_data)

    # 分析列信息
    columns_info = analyze_columns(df)

    # 插入文件元数据
    file_id = db.insert_file(
        user_id=session['user_id'],
        filename=filename,
        original_name=original_name,
        file_size=len(file_data),
        file_path=saved_path,
        row_count=len(df),
        col_count=len(df.columns),
        columns_info=columns_info,
    )

    # 逐行存入数据表
    db.insert_data_rows(file_id, df)

    # 自动选中该文件
    session['file_id'] = file_id

    return jsonify({
        "message": "上传成功",
        "file_id": file_id,
        "filename": original_name,
        "shape": {"rows": len(df), "cols": len(df.columns)},
        "columns": columns_info,
    })


# ==================== 文件列表与选择 ====================

@data_bp.route('/files', methods=['GET'])
@login_required
def list_files():
    """获取当前用户的上传文件列表"""
    files = db.get_user_files(session['user_id'])
    return jsonify({"files": files})


@data_bp.route('/files/<int:file_id>/select', methods=['POST'])
@login_required
def select_file(file_id):
    """选择要操作的文件"""
    file_info = db.get_file_by_id(file_id)
    if not file_info:
        return jsonify({"error": "文件不存在"}), 404
    user = db.get_user_by_id(session['user_id'])
    if file_info['user_id'] != session['user_id'] and user['role'] != 'admin':
        return jsonify({"error": "无权访问"}), 403

    session['file_id'] = file_id
    return jsonify({
        "message": "已选择文件",
        "file": file_info,
    })


@data_bp.route('/files/<int:file_id>', methods=['DELETE'])
@login_required
def delete_file_api(file_id):
    """删除文件"""
    file_info = db.get_file_by_id(file_id)
    if not file_info:
        return jsonify({"error": "文件不存在"}), 404
    user = db.get_user_by_id(session['user_id'])
    if file_info['user_id'] != session['user_id'] and user['role'] != 'admin':
        return jsonify({"error": "无权删除"}), 403

    db.delete_file(file_id)
    if session.get('file_id') == file_id:
        session.pop('file_id', None)
    return jsonify({"message": "文件已删除"})


@data_bp.route('/files/<int:file_id>/reset', methods=['POST'])
@login_required
def reset_file_api(file_id):
    """重置文件到原始状态"""
    file_info = db.get_file_by_id(file_id)
    if not file_info:
        return jsonify({"error": "文件不存在"}), 404
    user = db.get_user_by_id(session['user_id'])
    if file_info['user_id'] != session['user_id'] and user['role'] != 'admin':
        return jsonify({"error": "无权操作"}), 403

    file_path = file_info['file_path']
    if not file_path or not os.path.exists(file_path):
        return jsonify({"error": "原始文件已丢失，无法重置"}), 400

    try:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == '.csv':
            for encoding in ['utf-8', 'gbk', 'gb2312', 'latin-1']:
                try:
                    df = pd.read_csv(file_path, encoding=encoding)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                df = pd.read_csv(file_path, encoding='utf-8', errors='ignore')
        else:
            df = pd.read_excel(file_path)
    except Exception as e:
        return jsonify({"error": f"文件重新解析失败: {str(e)}"}), 500

    db.reset_data_rows(file_id, df)
    session['file_id'] = file_id

    return jsonify({
        "message": "数据已重置",
        "shape": {"rows": len(df), "cols": len(df.columns)},
        "columns": analyze_columns(df),
    })


# ==================== 数据预览与统计 ====================

@data_bp.route('/preview', methods=['GET'])
@require_file
def preview_data():
    """分页预览（从数据库读取）"""
    file_id = session['file_id']
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)

    file_info = db.get_file_by_id(file_id)
    if not file_info:
        return jsonify({"error": "文件不存在"}), 404

    # 读取全量有效行
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) as cnt FROM data_rows WHERE file_id = %s AND is_valid = 1",
        (file_id,)
    )
    total = cursor.fetchone()['cnt']

    offset = (page - 1) * per_page
    cursor.execute(
        "SELECT row_data FROM data_rows WHERE file_id = %s AND is_valid = 1 ORDER BY row_index LIMIT %s OFFSET %s",
        (file_id, per_page, offset)
    )
    rows = cursor.fetchall()
    conn.close()

    data = []
    for r in rows:
        row_data = r['row_data']
        if isinstance(row_data, str):
            row_data = json.loads(row_data)
        data.append(row_data)

    return jsonify({
        "data": data,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
        "columns": file_info['columns_info'],
        "cleaned": file_info['status'] == 'cleaned',
    })


@data_bp.route('/columns', methods=['GET'])
@require_file
def get_columns():
    """获取列信息"""
    file_info = db.get_file_by_id(session['file_id'])
    return jsonify({"columns": file_info['columns_info'] if file_info else []})


@data_bp.route('/stats', methods=['GET'])
@require_file
def get_stats():
    """获取统计信息"""
    df, cols, file_info = load_active_df()
    if df is None:
        return jsonify({"error": "无数据"}), 400

    desc = df.describe(include='all')
    stats_data = json.loads(desc.fillna("").to_json(force_ascii=False))

    col_details = {}
    for col in df.columns:
        detail = {
            "dtype": str(df[col].dtype),
            "missing": int(df[col].isna().sum()),
            "missing_pct": round(df[col].isna().sum() / max(len(df), 1) * 100, 2),
            "unique": int(df[col].nunique()),
        }
        if pd.api.types.is_numeric_dtype(df[col]):
            detail.update({
                "min": float(df[col].min()) if not pd.isna(df[col].min()) else None,
                "max": float(df[col].max()) if not pd.isna(df[col].max()) else None,
                "mean": round(float(df[col].mean()), 4) if not pd.isna(df[col].mean()) else None,
                "std": round(float(df[col].std()), 4) if not pd.isna(df[col].std()) else None,
                "q1": float(df[col].quantile(0.25)) if not pd.isna(df[col].quantile(0.25)) else None,
                "q3": float(df[col].quantile(0.75)) if not pd.isna(df[col].quantile(0.75)) else None,
            })
        col_details[col] = detail

    return jsonify({
        "describe": stats_data,
        "columns": col_details,
        "shape": {"rows": len(df), "cols": len(df.columns)},
    })


# ==================== 数据导出 ====================

@data_bp.route('/export', methods=['GET'])
@require_file
def export_data():
    """导出数据"""
    df, cols, file_info = load_active_df()
    if df is None:
        return jsonify({"error": "无数据"}), 400

    fmt = request.args.get('format', 'csv')
    fname = file_info['original_name'] if file_info else 'data'
    name_no_ext = os.path.splitext(fname)[0]

    buf = io.BytesIO()
    if fmt == 'xlsx':
        with pd.ExcelWriter(buf, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Data')
        buf.seek(0)
        return send_file(buf, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                         as_attachment=True,
                         download_name=f'{name_no_ext}_cleaned_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')
    else:
        df.to_csv(buf, index=False, encoding='utf-8-sig')
        buf.seek(0)
        return send_file(buf, mimetype='text/csv',
                         as_attachment=True,
                         download_name=f'{name_no_ext}_cleaned_{datetime.now().strftime("%Y%m%d_%H%M%S")}.csv')
