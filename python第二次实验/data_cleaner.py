# ============================================================
# 模块 2: 数据清洗模块 (data_cleaner.py)
# 功能：缺失值处理 / 异常值检测 / 去重 / 清洗历史
# ============================================================

import json

import numpy as np
import pandas as pd
from flask import Blueprint, request, jsonify, session
from scipy import stats

import db
from utils import require_file, analyze_columns, load_active_df

clean_bp = Blueprint('clean', __name__, url_prefix='/api')


@clean_bp.route('/clean', methods=['POST'])
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
                        df[col] = df[col].astype(float)
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


@clean_bp.route('/cleaning-history', methods=['GET'])
@require_file
def cleaning_history():
    """获取清洗历史"""
    logs = db.get_cleaning_logs(session['file_id'])
    return jsonify({"logs": logs})
