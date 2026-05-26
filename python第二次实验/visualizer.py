# ============================================================
# 模块 3: 可视化模块 (visualizer.py)
# 功能：动态生成多种图表（柱状图/折线图/散点图/饼图/直方图/箱线图/热力图/相关性矩阵）
# ============================================================

import io
import base64

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns
from flask import Blueprint, request, jsonify

from utils import require_file, load_active_df

# 中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
sns.set_style("whitegrid")

viz_bp = Blueprint('viz', __name__, url_prefix='/api')


@viz_bp.route('/visualize', methods=['POST'])
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


# ==================== 绘图函数 ====================

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
