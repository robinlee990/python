# ============================================================
# 模块 4: 分析功能模块 (analyzer.py)
# 功能：机器学习分析（K-Means 聚类 / 线性回归 / PCA 降维）
# ============================================================

import io
import json
import base64

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from flask import Blueprint, request, jsonify, session
from sklearn.cluster import KMeans
from sklearn.linear_model import LinearRegression
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler, LabelEncoder
from sklearn.model_selection import train_test_split
from sklearn.metrics import silhouette_score, mean_squared_error, r2_score

import db
from utils import require_file, df_to_json, load_active_df

analyze_bp = Blueprint('analyze', __name__, url_prefix='/api')


@analyze_bp.route('/analyze', methods=['POST'])
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

        image_base64 = result_data.get('image', '')

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


@analyze_bp.route('/analysis-history', methods=['GET'])
@require_file
def analysis_history():
    """获取分析历史"""
    analysis_type = request.args.get('type', None)
    results = db.get_analysis_results(session['file_id'], analysis_type)
    return jsonify({"results": results})


# ==================== 聚类分析 ====================

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


# ==================== 回归分析 ====================

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


# ==================== PCA 降维 ====================

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
