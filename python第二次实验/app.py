# ============================================================
# 交互式数据分析系统 - Flask 后端（数据库持久化版本）
# 功能：用户认证 → 上传 → 预览 → 清洗 → 可视化 → 分析 → 导出
# 数据全部存入 SQLite，关闭页面不丢失，支持多用户
# ============================================================

import os
import io
import json
import base64
import hashlib
from datetime import datetime
from functools import wraps

import numpy as np
import pandas as pd
from flask import (
    Flask, render_template, request, jsonify,
    session, send_file, make_response, redirect, url_for
)
from werkzeug.utils import secure_filename
from sklearn.cluster import KMeans
from sklearn.linear_model import LinearRegression
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import silhouette_score, mean_squared_error, r2_score
from scipy import stats
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

import db

# ---- 配置 ----
app = Flask(__name__)
app.secret_key = 'data-analysis-system-db-2024-secret-key'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'uploads')

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
sns.set_style("whitegrid")


# ==================== 装饰器 ====================

def login_required(f):
    """要求用户登录"""
    @wraps(f)
    def wrapper(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({"error": "请先登录"}), 401
        return f(*args, **kwargs)
    return wrapper


def require_file(f):
    """要求已选择文件（从数据库加载）"""
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


# ==================== 页面路由 ====================

@app.route('/')
def index():
    """主页：未登录跳转登录页"""
    if 'user_id' not in session:
        return render_template('index.html', logged_in=False)
    user = db.get_user_by_id(session['user_id'])
    return render_template('index.html', logged_in=True, user=user)


@app.route('/login')
def login_page():
    return render_template('index.html', logged_in=False)


# ==================== 用户认证 API ====================

@app.route('/api/auth/register', methods=['POST'])
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


@app.route('/api/auth/login', methods=['POST'])
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


@app.route('/api/auth/logout', methods=['POST'])
def api_logout():
    """退出登录"""
    session.clear()
    return jsonify({"message": "已退出"})


@app.route('/api/auth/me', methods=['GET'])
@login_required
def api_me():
    """获取当前用户信息"""
    user = db.get_user_by_id(session['user_id'])
    return jsonify({"user": user})


# ==================== 文件管理 API ====================

@app.route('/api/upload', methods=['POST'])
@login_required
def upload_file():
    """上传 CSV/Excel 文件并存入数据库"""
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

    # 保存原始文件到磁盘（用于重置/重新解析）
    saved_path = os.path.join(
        app.config['UPLOAD_FOLDER'],
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


@app.route('/api/files', methods=['GET'])
@login_required
def list_files():
    """获取当前用户的上传文件列表"""
    files = db.get_user_files(session['user_id'])
    return jsonify({"files": files})


@app.route('/api/files/<int:file_id>/select', methods=['POST'])
@login_required
def select_file(file_id):
    """选择要操作的文件"""
    file_info = db.get_file_by_id(file_id)
    if not file_info:
        return jsonify({"error": "文件不存在"}), 404
    # 允许管理员查看所有文件
    user = db.get_user_by_id(session['user_id'])
    if file_info['user_id'] != session['user_id'] and user['role'] != 'admin':
        return jsonify({"error": "无权访问"}), 403

    session['file_id'] = file_id
    return jsonify({
        "message": "已选择文件",
        "file": file_info,
    })


@app.route('/api/files/<int:file_id>', methods=['DELETE'])
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


@app.route('/api/files/<int:file_id>/reset', methods=['POST'])
@login_required
def reset_file_api(file_id):
    """重置文件到原始状态（从磁盘重新解析）"""
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


# ==================== 数据预览 & 统计 API ====================

@app.route('/api/preview', methods=['GET'])
@require_file
def preview_data():
    """分页预览（从数据库读取）"""
    file_id = session['file_id']
    page = request.args.get('page', 1, type=int)
    per_page = min(request.args.get('per_page', 50, type=int), 200)

    file_info = db.get_file_by_id(file_id)
    if not file_info:
        return jsonify({"error": "文件不存在"}), 404

    columns_info = file_info['columns_info']
    col_names = [c['name'] for c in columns_info]

    # 读取全量有效行
    conn = db.get_db()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT COUNT(*) as cnt FROM data_rows WHERE file_id = %s AND is_valid = 1",
        (file_id,)
    )
    total_row = cursor.fetchone()
    total = total_row['cnt']

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
        "columns": columns_info,
        "cleaned": file_info['status'] == 'cleaned',
    })


@app.route('/api/columns', methods=['GET'])
@require_file
def get_columns():
    file_info = db.get_file_by_id(session['file_id'])
    return jsonify({"columns": file_info['columns_info'] if file_info else []})


@app.route('/api/stats', methods=['GET'])
@require_file
def get_stats():
    """获取统计信息（从数据库加载 DataFrame 计算）"""
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


# ==================== 数据清洗 API ====================

@app.route('/api/clean', methods=['POST'])
@require_file
def clean_data():
    """数据清洗（结果持久化到数据库）"""
    df, cols, file_info = load_active_df()
    if df is None:
        return jsonify({"error": "无数据"}), 400

    file_id = session['file_id']
    params = request.get_json() or {}

    missing_strategy = params.get('missing_strategy', 'mean')
    missing_value = params.get('missing_value', 0)
    outlier_method = params.get('outlier_method', 'iqr')
    outlier_threshold = params.get('outlier_threshold', 1.5)
    outlier_action = params.get('outlier_action', 'cap')
    drop_duplicates = params.get('drop_duplicates', True)
    selected_columns = params.get('columns', None)

    numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
    cleaning_log = []
    rows_before = len(df)
    missing_before = int(df.isna().sum().sum())

    # ---- 删除缺失率超过 80% 的列 ----
    total_rows = len(df)
    cols_to_drop = []
    for col in df.columns:
        if selected_columns and col not in selected_columns:
            continue
        miss_rate = df[col].isna().sum() / total_rows
        if miss_rate > 0.8:
            cols_to_drop.append(col)
    if cols_to_drop:
        df = df.drop(columns=cols_to_drop)
        for col in cols_to_drop:
            cleaning_log.append(f"列 [{col}] 缺失值占比超过 80%，已删除该列")
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()

    # ---- 缺失值处理 ----
    if missing_strategy == 'drop':
        df = df.dropna()
        cleaning_log.append(f"删除含缺失值的行，共删除 {missing_before} 个缺失值所在的记录")
    else:
        for col in df.columns:
            if selected_columns and col not in selected_columns:
                continue
            miss_count = int(df[col].isna().sum())
            if miss_count > 0:
                if col in numeric_cols:
                    if missing_strategy == 'mean':
                        fill_val = df[col].mean()
                    elif missing_strategy == 'median':
                        fill_val = df[col].median()
                    elif missing_strategy == 'mode':
                        fill_val = df[col].mode().iloc[0] if len(df[col].mode()) > 0 else 0
                    else:
                        fill_val = missing_value
                else:
                    fill_val = df[col].mode().iloc[0] if len(df[col].mode()) > 0 else "未知"
                df[col] = df[col].fillna(fill_val)
                cleaning_log.append(f"列 [{col}] 的 {miss_count} 个缺失值已填充")

    missing_after = int(df.isna().sum().sum())

    # ---- 异常值处理 ----
    outlier_count = 0
    if outlier_method != 'none':
        for col in numeric_cols:
            if selected_columns and col not in selected_columns:
                continue
            col_data = df[col].dropna()
            if len(col_data) < 4:
                continue
            if outlier_method == 'iqr':
                Q1 = col_data.quantile(0.25)
                Q3 = col_data.quantile(0.75)
                IQR = Q3 - Q1
                lower = Q1 - outlier_threshold * IQR
                upper = Q3 + outlier_threshold * IQR
                outliers_mask = (df[col] < lower) | (df[col] > upper)
            elif outlier_method == 'zscore':
                z = np.abs(stats.zscore(col_data))
                outliers_mask = pd.Series(False, index=df.index)
                outliers_mask.loc[col_data.index[z > outlier_threshold]] = True

            n_out = int(outliers_mask.sum())
            if n_out > 0:
                outlier_count += n_out
                if outlier_action == 'cap':
                    if outlier_method == 'iqr':
                        df[col] = df[col].astype(float)  # 先转浮点，避免 int64 无法赋值 float 边界值
                        df.loc[df[col] < lower, col] = lower
                        df.loc[df[col] > upper, col] = upper
                    cleaning_log.append(f"列 [{col}] 检测到 {n_out} 个异常值，已用边界值替换")
                elif outlier_action == 'remove':
                    df = df[~outliers_mask]
                    cleaning_log.append(f"列 [{col}] 移除了 {n_out} 个异常值")

    # ---- 去重 ----
    if drop_duplicates:
        before_dedup = len(df)
        df = df.drop_duplicates()
        after_dedup = len(df)
        if before_dedup != after_dedup:
            cleaning_log.append(f"删除了 {before_dedup - after_dedup} 条重复记录")

    rows_after = len(df)

    # ---- 存入数据库 ----
    new_columns_info = analyze_columns(df)
    db.update_data_rows_after_clean(file_id, df)
    db.update_file_status(file_id, 'cleaned', row_count=rows_after,
                          col_count=len(df.columns), columns_info=new_columns_info)

    # 记录清洗日志
    db.insert_cleaning_log(
        file_id=file_id,
        user_id=session['user_id'],
        operation_logs=cleaning_log,
        missing_before=missing_before,
        missing_after=missing_after,
        outliers_found=outlier_count,
        rows_before=rows_before,
        rows_after=rows_after,
        params_json=params,
    )

    return jsonify({
        "message": "数据清洗完成",
        "cleaning_log": cleaning_log,
        "missing_before": missing_before,
        "missing_after": missing_after,
        "outliers_found": outlier_count,
        "shape_before": {"rows": rows_before, "cols": len(df.columns)},
        "shape_after": {"rows": rows_after, "cols": len(df.columns)},
        "columns": new_columns_info,
        "stats": json.loads(df.describe(include='all').fillna("").to_json(force_ascii=False)),
    })


@app.route('/api/cleaning-history', methods=['GET'])
@require_file
def cleaning_history():
    """获取清洗历史"""
    logs = db.get_cleaning_logs(session['file_id'])
    return jsonify({"logs": logs})


# ==================== 可视化 API ====================

@app.route('/api/visualize', methods=['POST'])
@require_file
def visualize():
    """生成图表"""
    df, cols, file_info = load_active_df()
    if df is None:
        return jsonify({"error": "无数据"}), 400

    params = request.get_json() or {}
    chart_type = params.get('chart_type', 'bar')
    x_col = params.get('x_col')
    y_col = params.get('y_col')
    title = params.get('title', f'{chart_type.upper()} Chart')
    color = params.get('color', '#4A90D9')
    top_n = params.get('top_n', 10)

    if x_col and x_col not in df.columns:
        return jsonify({"error": f"列 '{x_col}' 不存在"}), 400
    if y_col and y_col not in df.columns:
        return jsonify({"error": f"列 '{y_col}' 不存在"}), 400

    try:
        plt.close('all')
        fig, ax = plt.subplots(figsize=(10, 6))

        if chart_type == 'bar':
            _draw_bar(df, ax, x_col, y_col, title, color, top_n)
        elif chart_type == 'line':
            _draw_line(df, ax, x_col, y_col, title, color, top_n)
        elif chart_type == 'scatter':
            _draw_scatter(df, ax, x_col, y_col, title, color)
        elif chart_type == 'pie':
            _draw_pie(df, ax, x_col, title, top_n)
        elif chart_type == 'histogram':
            _draw_histogram(df, ax, x_col, title, color)
        elif chart_type == 'box':
            _draw_box(df, ax, x_col, y_col, title, color)
        elif chart_type == 'heatmap':
            fig, ax = plt.subplots(figsize=(12, 8))
            _draw_heatmap(df, fig, ax, title)
        elif chart_type == 'correlation':
            fig, ax = plt.subplots(figsize=(10, 8))
            _draw_correlation(df, fig, ax, title)
        else:
            return jsonify({"error": f"不支持的图表类型: {chart_type}"}), 400

        plt.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=120, bbox_inches='tight')
        buf.seek(0)
        img_base64 = base64.b64encode(buf.read()).decode('utf-8')
        plt.close('all')

        return jsonify({
            "image": f"data:image/png;base64,{img_base64}",
            "chart_type": chart_type,
        })
    except Exception as e:
        plt.close('all')
        return jsonify({"error": f"图表生成失败: {str(e)}"}), 500


# ---- 绘图函数 ----
def _draw_bar(df, ax, x_col, y_col, title, color, top_n):
    if y_col:
        data = df.groupby(x_col)[y_col].sum().nlargest(top_n).reset_index()
        ax.bar(data[x_col].astype(str), data[y_col], color=color, edgecolor='white')
    else:
        counts = df[x_col].value_counts().nlargest(top_n)
        ax.bar(counts.index.astype(str), counts.values, color=color, edgecolor='white')
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col if y_col else 'Count')
    plt.xticks(rotation=45, ha='right')


def _draw_line(df, ax, x_col, y_col, title, color, top_n):
    if x_col and y_col:
        if pd.api.types.is_numeric_dtype(df[x_col]):
            data = df.sort_values(x_col).head(top_n)
        else:
            data = df.groupby(x_col)[y_col].mean().nlargest(top_n).reset_index()
        ax.plot(data[x_col].astype(str), data[y_col], marker='o',
                color=color, linewidth=2, markersize=6)
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col if y_col else '')
    ax.grid(True, alpha=0.3)
    plt.xticks(rotation=45, ha='right')


def _draw_scatter(df, ax, x_col, y_col, title, color):
    if x_col and y_col:
        ax.scatter(df[x_col], df[y_col], alpha=0.6, c=color, edgecolors='white', s=50)
        if pd.api.types.is_numeric_dtype(df[x_col]) and pd.api.types.is_numeric_dtype(df[y_col]):
            try:
                m, b = np.polyfit(df[x_col].dropna(), df[y_col].dropna(), 1)
                ax.plot(df[x_col], m * df[x_col] + b, color='red', linewidth=1.5, linestyle='--')
            except:
                pass
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlabel(x_col)
    ax.set_ylabel(y_col)
    ax.grid(True, alpha=0.3)


def _draw_pie(df, ax, x_col, title, top_n):
    counts = df[x_col].value_counts().nlargest(top_n)
    colors = plt.cm.Set3(np.linspace(0, 1, len(counts)))
    wedges, texts, autotexts = ax.pie(
        counts.values, labels=counts.index, autopct='%1.1f%%',
        colors=colors, startangle=90
    )
    for t in autotexts:
        t.set_fontsize(9)
    ax.set_title(title, fontsize=14, fontweight='bold')


def _draw_histogram(df, ax, x_col, title, color):
    if x_col and x_col in df.columns:
        ax.hist(df[x_col].dropna(), bins=20, color=color, edgecolor='white', alpha=0.8)
        m = df[x_col].mean()
        md = df[x_col].median()
        ax.axvline(m, color='red', linestyle='--', linewidth=1.5, label=f'均值: {m:.2f}')
        ax.axvline(md, color='green', linestyle='--', linewidth=1.5, label=f'中位数: {md:.2f}')
        ax.legend()
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.set_xlabel(x_col)
    ax.set_ylabel('频数')


def _draw_box(df, ax, x_col, y_col, title, color):
    if x_col and y_col:
        top_cats = df[x_col].value_counts().nlargest(10).index
        subset = df[df[x_col].isin(top_cats)]
        subset.boxplot(column=y_col, by=x_col, ax=ax, grid=False)
        ax.set_title(title, fontsize=14, fontweight='bold')
        ax.set_xlabel(x_col)
        ax.set_ylabel(y_col)
        plt.xticks(rotation=45, ha='right')


def _draw_heatmap(df, fig, ax, title):
    numeric_df = df.select_dtypes(include=[np.number])
    if numeric_df.shape[1] >= 2:
        sns.heatmap(numeric_df.corr(), annot=True, fmt='.2f', cmap='coolwarm',
                     ax=ax, square=True, linewidths=0.5)
    else:
        ax.text(0.5, 0.5, '数值列不足', ha='center', va='center', fontsize=14)
    ax.set_title(title, fontsize=14, fontweight='bold')


def _draw_correlation(df, fig, ax, title):
    numeric_df = df.select_dtypes(include=[np.number])
    if numeric_df.shape[1] >= 2:
        corr = numeric_df.corr()
        mask = np.triu(np.ones_like(corr, dtype=bool))
        sns.heatmap(corr, mask=mask, annot=True, fmt='.2f', cmap='RdBu_r',
                     ax=ax, square=True, linewidths=0.5, center=0, vmin=-1, vmax=1)
    else:
        ax.text(0.5, 0.5, '数值列不足', ha='center', va='center', fontsize=14)
    ax.set_title(title, fontsize=14, fontweight='bold')


# ==================== 机器学习分析 API ====================

@app.route('/api/analyze', methods=['POST'])
@require_file
def analyze():
    """机器学习分析（结果存入数据库）"""
    df, cols, file_info = load_active_df()
    if df is None:
        return jsonify({"error": "无数据"}), 400

    file_id = session['file_id']
    params = request.get_json() or {}
    analysis_type = params.get('type', 'clustering')
    columns = params.get('columns', [])
    target = params.get('target', '')
    n_clusters = params.get('n_clusters', 3)

    try:
        if analysis_type == 'clustering':
            result = _do_clustering(df, columns, n_clusters)
        elif analysis_type == 'regression':
            result = _do_regression(df, columns, target)
        elif analysis_type == 'pca':
            result = _do_pca(df, columns)
        else:
            return jsonify({"error": f"不支持的分析类型: {analysis_type}"}), 400

        # 解析结果，保存到数据库
        result_json = result.get_json()
        if isinstance(result_json, str):
            result_data = json.loads(result_json)
        else:
            result_data = result_json

        # 提取 image 存到数据库
        image_base64 = result_data.get('image', '')

        # 保存分析结果到数据库
        db.insert_analysis_result(
            file_id=file_id,
            user_id=session['user_id'],
            analysis_type=analysis_type,
            parameters=params,
            result_data=result_data,
            image_base64=image_base64,
        )

        return result
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({"error": f"分析失败: {str(e)}"}), 500


@app.route('/api/analysis-history', methods=['GET'])
@require_file
def analysis_history():
    """获取分析历史"""
    analysis_type = request.args.get('type', None)
    results = db.get_analysis_results(session['file_id'], analysis_type)
    return jsonify({"results": results})


def _do_clustering(df, columns, n_clusters):
    if not columns:
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        columns = numeric_cols[:min(len(numeric_cols), 5)]
    else:
        columns = [c for c in columns if c in df.columns]

    if len(columns) < 2:
        return jsonify({"error": "聚类分析至少需要 2 个数值列"}), 400

    data = df[columns].dropna().copy()
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(data)

    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X_scaled)

    sil_score = silhouette_score(X_scaled, labels) if len(set(labels)) > 1 else 0

    centers = scaler.inverse_transform(kmeans.cluster_centers_)
    centers_dict = {}
    for i, center in enumerate(centers):
        centers_dict[f"簇 {i}"] = {columns[j]: round(float(center[j]), 4) for j in range(len(columns))}

    cluster_counts = pd.Series(labels).value_counts().sort_index().to_dict()
    cluster_counts = {f"簇 {k}": int(v) for k, v in cluster_counts.items()}

    df_result = data.copy()
    df_result['Cluster'] = labels.astype(str)

    # 可视化
    plt.close('all')
    img_base64 = None
    if len(columns) >= 2:
        fig, axes = plt.subplots(1, 2, figsize=(14, 6))
        scatter = axes[0].scatter(data[columns[0]], data[columns[1]],
                                   c=labels, cmap='viridis', alpha=0.6, s=40)
        axes[0].set_xlabel(columns[0])
        axes[0].set_ylabel(columns[1])
        axes[0].set_title(f'K-Means 聚类结果 (n={n_clusters})', fontsize=12, fontweight='bold')
        plt.colorbar(scatter, ax=axes[0], label='Cluster')
        sizes = [cluster_counts.get(f"簇 {i}", 0) for i in range(n_clusters)]
        axes[1].pie(sizes, labels=[f'簇 {i}' for i in range(n_clusters)],
                     autopct='%1.1f%%', startangle=90,
                     colors=plt.cm.viridis(np.linspace(0, 1, n_clusters)))
        axes[1].set_title('各簇样本分布', fontsize=12, fontweight='bold')
        plt.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format='png', dpi=120, bbox_inches='tight')
        buf.seek(0)
        img_base64 = f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
        plt.close('all')

    return jsonify({
        "type": "clustering",
        "algorithm": "K-Means",
        "n_clusters": n_clusters,
        "silhouette_score": round(sil_score, 4),
        "cluster_centers": centers_dict,
        "cluster_counts": cluster_counts,
        "columns_used": columns,
        "image": img_base64,
        "sample_data": df_to_json(df_result.head(100)),
    })


def _do_regression(df, columns, target):
    if not target or target not in df.columns:
        return jsonify({"error": "请选择有效的目标列"}), 400

    if not columns:
        numeric_cols = [c for c in df.select_dtypes(include=[np.number]).columns.tolist() if c != target]
        columns = numeric_cols[:min(len(numeric_cols), 5)]
    columns = [c for c in columns if c in df.columns and c != target]

    if len(columns) < 1:
        return jsonify({"error": "至少需要 1 个特征列"}), 400

    data = df[columns + [target]].dropna().copy()
    X = data[columns]
    y = data[target]

    for col in X.columns:
        if not pd.api.types.is_numeric_dtype(X[col]):
            X[col] = LabelEncoder().fit_transform(X[col].astype(str))

    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.2, random_state=42)
    model = LinearRegression()
    model.fit(X_train, y_train)
    y_pred = model.predict(X_test)

    mse = mean_squared_error(y_test, y_pred)
    r2 = r2_score(y_test, y_pred)

    coefficients = {col: round(float(coef), 6) for col, coef in zip(columns, model.coef_)}
    coefficients['截距'] = round(float(model.intercept_), 6)

    # 可视化
    plt.close('all')
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    axes[0].scatter(y_test, y_pred, alpha=0.6, edgecolors='white')
    axes[0].plot([y.min(), y.max()], [y.min(), y.max()], 'r--', linewidth=2)
    axes[0].set_xlabel('实际值')
    axes[0].set_ylabel('预测值')
    axes[0].set_title(f'预测 vs 实际 (R²={r2:.4f})', fontsize=12, fontweight='bold')
    axes[0].grid(True, alpha=0.3)

    coef_df = pd.DataFrame({'特征': columns, '系数': [abs(float(c)) for c in model.coef_]})
    coef_df = coef_df.sort_values('系数', ascending=True)
    colors_bar = ['#2ecc71' if c > 0 else '#e74c3c' for c in model.coef_]
    axes[1].barh(coef_df['特征'], coef_df['系数'], color=colors_bar, edgecolor='white')
    axes[1].set_title('特征系数（绝对值）', fontsize=12, fontweight='bold')
    axes[1].set_xlabel('|系数|')

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight')
    buf.seek(0)
    img_base64 = f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
    plt.close('all')

    return jsonify({
        "type": "regression",
        "algorithm": "Linear Regression",
        "mse": round(mse, 4),
        "rmse": round(np.sqrt(mse), 4),
        "r2_score": round(r2, 4),
        "coefficients": coefficients,
        "features": columns,
        "target": target,
        "train_size": len(X_train),
        "test_size": len(X_test),
        "image": img_base64,
    })


def _do_pca(df, columns):
    if not columns:
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        columns = numeric_cols[:min(len(numeric_cols), 10)]
    columns = [c for c in columns if c in df.columns]

    if len(columns) < 2:
        return jsonify({"error": "PCA 至少需要 2 个数值列"}), 400

    data = df[columns].dropna().copy()
    scaler = StandardScaler()
    X_scaled = scaler.fit_transform(data)

    n_components = min(len(columns), 5)
    pca = PCA(n_components=n_components)
    X_pca = pca.fit_transform(X_scaled)

    explained_var = [round(float(v), 4) for v in pca.explained_variance_ratio_]
    cumsum_var = [round(float(v), 4) for v in np.cumsum(pca.explained_variance_ratio_)]

    loadings = {}
    for i in range(n_components):
        loadings[f"PC{i+1}"] = {
            columns[j]: round(float(pca.components_[i][j]), 4)
            for j in range(len(columns))
        }

    # 可视化
    plt.close('all')
    fig, axes = plt.subplots(1, 2, figsize=(14, 6))
    x = range(1, n_components + 1)
    axes[0].bar(x, explained_var, alpha=0.7, color='#4A90D9', label='Individual', edgecolor='white')
    axes[0].plot(x, cumsum_var, 'ro-', linewidth=2, label='Cumulative')
    axes[0].set_xlabel('主成分')
    axes[0].set_ylabel('解释方差比')
    axes[0].set_title('PCA 方差解释', fontsize=12, fontweight='bold')
    axes[0].legend()
    axes[0].set_xticks(x)

    if n_components >= 2:
        axes[1].scatter(X_pca[:, 0], X_pca[:, 1], alpha=0.6, c='#4A90D9', edgecolors='white')
        axes[1].set_xlabel(f'PC1 ({explained_var[0]*100:.1f}%)')
        axes[1].set_ylabel(f'PC2 ({explained_var[1]*100:.1f}%)')
        axes[1].set_title('PCA 前两个主成分', fontsize=12, fontweight='bold')
        axes[1].grid(True, alpha=0.3)

    plt.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight')
    buf.seek(0)
    img_base64 = f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
    plt.close('all')

    pca_cols = [f"PC{i+1}" for i in range(n_components)]
    result_df = pd.DataFrame(X_pca, columns=pca_cols)

    return jsonify({
        "type": "pca",
        "algorithm": "PCA",
        "n_components": n_components,
        "explained_variance_ratio": explained_var,
        "cumulative_variance": cumsum_var,
        "loadings": loadings,
        "columns_used": columns,
        "image": img_base64,
        "sample_data": df_to_json(result_df.head(100)),
    })


# ==================== 导出 API ====================

@app.route('/api/export', methods=['GET'])
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


# ==================== 用户管理 API（管理员） ====================

@app.route('/api/admin/users', methods=['GET'])
@login_required
def admin_list_users():
    user = db.get_user_by_id(session['user_id'])
    if user['role'] != 'admin':
        return jsonify({"error": "无权限"}), 403
    return jsonify({"users": db.get_all_users()})


@app.route('/api/admin/files', methods=['GET'])
@login_required
def admin_list_files():
    user = db.get_user_by_id(session['user_id'])
    if user['role'] != 'admin':
        return jsonify({"error": "无权限"}), 403
    return jsonify({"files": db.get_all_files()})


# ==================== 启动 ====================

if __name__ == '__main__':
    print("=" * 60)
    print("  交互式数据分析系统 - 数据库持久化版")
    print("  访问地址: http://127.0.0.1:8000")
    print("  默认管理员: admin / admin123")
    print("=" * 60)
    app.run(debug=True, host='0.0.0.0', port=8000)
