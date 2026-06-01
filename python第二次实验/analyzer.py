# ============================================================
# 模块 4: 分析功能模块 (analyzer.py)
# 功能：聚类分析（K-Means / DBSCAN），含基于实际值的评估

# ============================================================

import io
import json
import base64

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# 配置中文字体，解决图表中文显示为方框的问题
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False
from flask import Blueprint, request, jsonify, session
# Blueprint: Flask的蓝图对象，用于模块化组织路由，将不同功能的API分组管理
# request: 请求对象，包含客户端发送的所有HTTP请求信息（如GET/POST参数、JSON数据等）
# jsonify: 将Python字典或列表转换为JSON格式的响应，方便前端接收
# session: 会话对象，用于在服务器端存储用户会话数据（如登录状态、用户ID等）
from sklearn.cluster import KMeans, DBSCAN
# KMeans: K均值聚类算法
# 基于距离的迭代聚类方法
# 需要预先指定聚类数量K
# 适用于球形分布的数据簇
# 计算效率高，适合大数据集
# DBSCAN: 基于密度的聚类算法
# 不需要预先指定聚类数量
# 能发现任意形状的簇
# 可以识别噪声点（离群值）
# 基于两个参数：eps（邻域半径）和min_samples（最小样本数）
from sklearn.preprocessing import StandardScaler, LabelEncoder, OneHotEncoder
# StandardScaler: 标准化处理
# 将数据转换为均值为0、标准差为1的标准正态分布
# 公式：(x - mean) / std
# 消除不同特征量纲的影响，对聚类等距离敏感算法很重要
# LabelEncoder: 标签编码
# 将分类变量转换为整数编码
# 例如：["男", "女"] → [0, 1]
# 适用于有序分类或树模型
# OneHotEncoder: 独热编码
# 将分类变量转换为二进制向量
# 例如：["红", "绿", "蓝"] → [[1,0,0], [0,1,0], [0,0,1]]
# 避免引入虚假的顺序关系，适用于无序分类变量
from sklearn.compose import ColumnTransformer  # 列转换器
from sklearn.metrics import silhouette_score, adjusted_rand_score, normalized_mutual_info_score, homogeneity_score, completeness_score, v_measure_score
# silhouette_score: 轮廓系数
# 衡量聚类的紧密度和分离度
# 取值范围：[-1, 1]，越接近1越好
# 不需要真实标签，无监督评估
# adjusted_rand_score: 调整兰德指数
# 比较预测聚类与真实标签的一致性
# 取值范围：[-1, 1]，1表示完美匹配
# 需要真实标签，有监督评估
# normalized_mutual_info_score: 标准化互信息
# 基于信息论的聚类评估指标
# 衡量两个标签分布的相互依赖程度
# 取值范围：[0, 1]，1表示完全相关
# homogeneity_score: 同质性得分
# 每个簇只包含单一类别的样本
# 取值范围：[0, 1]，1表示完全同质
# completeness_score: 完整性得分
# 同一类别的所有样本都在同一个簇中
# 取值范围：[0, 1]，1表示完全完整
# v_measure_score: V-measure得分
# 同质性和完整性的调和平均
# 综合评估聚类质量
# 取值范围：[0, 1]，1表示最佳

import db
from utils import require_file, df_to_json, load_active_df

analyze_bp = Blueprint('analyze', __name__, url_prefix='/api')


# ==================== 数据编码工具函数 ====================

def _encode_mixed_columns(df, columns):
    """
    将混合类型列（数值+非数值）统一编码为可用于聚类的数值矩阵。
    
    流程：
    1. 分离数值列和非数值列
    2. 数值列：用 StandardScaler 标准化
    3. 非数值列：用 OneHotEncoder 编码（限制每个类别列最多 max_categories 个类别）
    4. 将编码后的所有列拼接为统一矩阵
    
    返回:
        X_encoded: 编码后的数值矩阵 (numpy array)
        encoded_col_names: 编码后各列的显示名称列表
        preprocessor: ColumnTransformer 对象（包含 scaler 和 encoder）
    """
    numeric_cols = []
    categorical_cols = []
    
    for col in columns:
        if col not in df.columns:
            continue
        if pd.api.types.is_numeric_dtype(df[col]):
            numeric_cols.append(col)
        else:
            # 非数值列作为类别列处理
            categorical_cols.append(col)
    
    if not numeric_cols and not categorical_cols:
        raise ValueError("没有可用的列进行聚类分析")
    
    transformers = []
    encoded_col_names = []
    
    # 数值列标准化
    if numeric_cols:
        scaler = StandardScaler()
        transformers.append(('num', scaler, numeric_cols))
        encoded_col_names.extend(numeric_cols)
    
    # 非数值列 One-Hot 编码
    if categorical_cols:
        # 限制每个类别列的类别数量，避免维度爆炸
        max_categories = 20
        encoder = OneHotEncoder(sparse_output=False, handle_unknown='ignore',
                                max_categories=max_categories, drop=None)
        # 创建独热编码器，将分类变量转换为二进制向量：
        # sparse_output=False：返回稠密数组而非稀疏矩阵
        # handle_unknown='ignore'：遇到未知类别时全置0，不报错
        # max_categories=20：每列最多编码20个类别，防止维度爆炸
        # drop=None：保留所有类别，不进行多重共线性处理
        transformers.append(('cat', encoder, categorical_cols))
        
        # 生成 One-Hot 编码后的列名
        for col in categorical_cols:
            unique_vals = df[col].dropna().unique()
            n_cats = min(len(unique_vals), max_categories)
            # 按出现频率排序取前 max_categories
            top_vals = df[col].value_counts().head(max_categories).index.tolist()
            for val in top_vals:
                encoded_col_names.append(f"{col}={str(val)[:20]}")
            # 如果有被截断的类别，加一个 other 列
            if len(unique_vals) > max_categories:
                encoded_col_names.append(f"{col}=_其他")
    
    if not transformers:
        raise ValueError("没有可用的列进行聚类分析")
    
    preprocessor = ColumnTransformer(
        transformers=transformers,   # 应用之前配置的标准化器和编码器到对应列
        remainder='drop'    # 丢弃未在transformers中指定的列
    )
    
    # 处理数据并编码
    data = df[columns].copy()
    # 类别列的空值用众数填充
    for col in categorical_cols:
        if data[col].isna().any():
            mode_val = data[col].mode()
            fill_val = mode_val[0] if len(mode_val) > 0 else "未知"
            data[col] = data[col].fillna(fill_val)
    
    X_encoded = preprocessor.fit_transform(data)   # 纯数值NumPy数组
    
    # 再次确保 encoded_col_names 长度与 X_encoded 列数一致
    # OneHotEncoder 可能因为 handle_unknown 产生额外列
    if hasattr(preprocessor, 'named_transformers_'):
        cat_transformer = preprocessor.named_transformers_.get('cat')
        if cat_transformer and hasattr(cat_transformer, 'get_feature_names_out'):
            cat_names = cat_transformer.get_feature_names_out(categorical_cols)
            encoded_col_names = numeric_cols + list(cat_names)
    
    return X_encoded, encoded_col_names, preprocessor


@analyze_bp.route('/analyze', methods=['POST'])
@require_file
def analyze():
    """聚类分析（结果存入数据库）"""
    df, cols, file_info = load_active_df()
    if df is None:
        return jsonify({"error": "无数据"}), 400

    file_id = session['file_id']
    params = request.get_json() or {}
    columns = params.get('columns', [])
    n_clusters = params.get('n_clusters', 3)
    algorithm = params.get('algorithm', 'kmeans')
    ground_truth_col = params.get('ground_truth_col', '')  # 用于与实际值对比的列

    try:
        if algorithm == 'dbscan':
            result = _do_clustering_dbscan(df, columns, ground_truth_col)
        else:
            result = _do_clustering_kmeans(df, columns, n_clusters, ground_truth_col)

        # 解析结果，保存到数据库
        result_json = result.get_json()
        if isinstance(result_json, str):
            result_data = json.loads(result_json)    # 转换为字典
        else:
            result_data = result_json

        image_base64 = result_data.get('image', '')

        db.insert_analysis_result(
            file_id=file_id,
            user_id=session['user_id'],
            analysis_type='clustering',
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
    return jsonify({"results": results})    # 返回包含results键的JSON对象给前端


# ==================== 基于实际值的评估函数 ====================

def _evaluate_with_ground_truth(labels, df_original, ground_truth_col, columns, n_samples):
    """
    使用数据集中的实际分类列对聚类结果进行评估。
    将实际分类列编码为数值标签后，与聚类标签进行对比。
    返回多项外部评估指标。
    """
    if not ground_truth_col or ground_truth_col not in df_original.columns:
        return None

    # 获取与聚类数据对应的实际标签
    common_idx = df_original[columns].dropna().index
    gt_series = df_original.loc[common_idx, ground_truth_col].dropna()
    common_idx = gt_series.index
    gt_values = gt_series.values

    if len(gt_values) < 2:
        return None

    # 将实际分类值编码为数值标签
    le = LabelEncoder()
    gt_labels = le.fit_transform(gt_values.astype(str))

    # 只取对应行的聚类标签
    idx_map = {v: i for i, v in enumerate(df_original[columns].dropna().index)}   # 构建原始数据索引到数组位置的映射字典
    label_indices = [idx_map[idx] for idx in common_idx if idx in idx_map]    # 收集所有符合条件的位置到 label_indices 列表
    cluster_labels_aligned = labels[label_indices]    # 使用NumPy高级索引提取对齐后的聚类标签：label_indices 包含有效样本的位置列表,从完整聚类标签数组中选取对应位置的元素



    n_classes = len(set(gt_labels))
    n_clusters = len(set(cluster_labels_aligned))

    evaluation = {
        "ground_truth_column": ground_truth_col,
        "ground_truth_classes": int(n_classes),
        "ground_truth_labels": [str(x) for x in le.classes_],
    }

    if n_classes > 1 and n_clusters > 1:
        try:
            evaluation["adjusted_rand_score"] = round(adjusted_rand_score(gt_labels, cluster_labels_aligned), 4)
        except:
            evaluation["adjusted_rand_score"] = None
        try:
            evaluation["normalized_mutual_info"] = round(normalized_mutual_info_score(gt_labels, cluster_labels_aligned), 4)
        except:
            evaluation["normalized_mutual_info"] = None
        try:
            evaluation["homogeneity"] = round(homogeneity_score(gt_labels, cluster_labels_aligned), 4)
        except:
            evaluation["homogeneity"] = None
        try:
            evaluation["completeness"] = round(completeness_score(gt_labels, cluster_labels_aligned), 4)
        except:
            evaluation["completeness"] = None
        try:
            evaluation["v_measure"] = round(v_measure_score(gt_labels, cluster_labels_aligned), 4)
        except:
            evaluation["v_measure"] = None
    else:
        evaluation["adjusted_rand_score"] = None
        evaluation["normalized_mutual_info"] = None
        evaluation["homogeneity"] = None
        evaluation["completeness"] = None
        evaluation["v_measure"] = None

    # 计算各簇中实际类别的分布（交叉表）
    try:
        ct = pd.crosstab(cluster_labels_aligned, gt_labels)   # 创建交叉列联表
        ct.index = [f"簇 {i}" for i in ct.index]    # 重命名行索引为可读格式
        ct.columns = [str(le.classes_[i]) for i in ct.columns]    # 重命名列名为真实的类别名称，le.classes_是LabelEncoder学习的类别映射
        evaluation["cluster_ground_truth_distribution"] = ct.to_dict()   # 将DataFrame转换为嵌套字典，添加到评估结果中

    except:
        evaluation["cluster_ground_truth_distribution"] = {}

    return evaluation

# ==================== 通用聚类可视化 ====================

def _build_clustering_chart(X_2d, labels, columns, encoded_col_names, n_clusters, algorithm_name, cluster_counts, eps=None):
    """
    通用聚类可视化函数。
    
    使用 PCA 将高维编码数据降维到 2D 进行可视化，
    兼容数值列和 One-Hot 编码列混合的场景。
    """
    from sklearn.decomposition import PCA
    
    plt.close('all')
    
    n_samples = len(labels)
    # 对数据做 PCA 降维到 2D
    if X_2d.shape[1] >= 2:
        pca = PCA(n_components=2)
        coords = pca.fit_transform(X_2d)
        var1, var2 = pca.explained_variance_ratio_[:2]    # 获取前两个主成分的解释方差比例，表示每个主成分保留了多少原始数据的信息
    else:
        # 只有一维，复制一列做 Y 轴
        coords = np.column_stack([X_2d[:, 0], np.zeros(n_samples)])
        var1, var2 = 1.0, 0.0
    
    fig, axes = plt.subplots(1, 2, figsize=(16, 6))
    
    # 子图1：PCA 降维后的聚类散点图
    unique_labels = sorted(set(labels))
    n_uniq = max(len(unique_labels), 1)
    
    if algorithm_name == 'DBSCAN':
        colors = plt.cm.tab10(np.linspace(0, 1, n_uniq))
        for lbl, color in zip(unique_labels, colors):
            mask = labels == lbl
            label_name = "噪声点" if lbl == -1 else f"簇 {lbl}"
            marker = 'x' if lbl == -1 else 'o'
            size = 30 if lbl == -1 else 40
            axes[0].scatter(coords[mask, 0], coords[mask, 1],
                            c=[color], label=label_name, alpha=0.7,
                            s=size, marker=marker)
        title_suffix = f'(eps={eps:.2f})' if eps else ''
        axes[0].set_title(f'DBSCAN 聚类结果 (PCA降维) {title_suffix}', fontsize=12, fontweight='bold')
        axes[0].legend(fontsize=8, loc='best')
    else:
        scatter = axes[0].scatter(coords[:, 0], coords[:, 1],
                                  c=labels, cmap='viridis', alpha=0.6, s=40)
        axes[0].set_title(f'K-Means 聚类结果 (K={n_clusters}, PCA降维)', fontsize=12, fontweight='bold')
        plt.colorbar(scatter, ax=axes[0], label='Cluster')
    
    axes[0].set_xlabel(f'PC1 ({var1*100:.1f}%)')
    axes[0].set_ylabel(f'PC2 ({var2*100:.1f}%)')
    
    # 子图2：各簇样本分布饼图
    sizes = []
    pie_labels = []
    for lbl in unique_labels:
        pie_labels.append(f"簇 {lbl}" if lbl != -1 else "噪声点")
        sizes.append(int(np.sum(labels == lbl)))
    pie_colors = plt.cm.tab10(np.linspace(0, 1, n_uniq)) if algorithm_name == 'DBSCAN' else plt.cm.viridis(np.linspace(0, 1, n_uniq))
    axes[1].pie(sizes, labels=pie_labels, autopct='%1.1f%%',
                startangle=90, colors=pie_colors[:n_uniq])
    axes[1].set_title('各簇样本分布', fontsize=12, fontweight='bold')
    
    # 在图表底部添加编码列信息
    fig.text(0.5, 0.01, f'分析列(原始): {", ".join(columns[:10])}{"..." if len(columns) > 10 else ""} | 编码后维度: {X_2d.shape[1]}',
             ha='center', fontsize=7, color='gray', style='italic')
    
    plt.tight_layout(rect=[0, 0.03, 1, 1])
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight')
    buf.seek(0)
    img_base64 = f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
    plt.close('all')
    
    return img_base64


def _build_ground_truth_chart_v2(X_encoded, labels, ground_truth_col, df_original, algorithm_name, encoded_col_names):
    """
    使用 PCA 降维 + 实际值对比的可视化图表（兼容混合类型列）。
    """
    from sklearn.decomposition import PCA
    
    plt.close('all')
    
    # 对齐 ground truth 数据
    data_subset = df_original[df_original.index.isin(df_original.dropna(subset=[ground_truth_col]).index)].copy()
    gt_series = data_subset[ground_truth_col].dropna()
    common_idx = gt_series.index
    
    # 需要确保 X_encoded 和 common_idx 对齐
    all_valid_idx = df_original.dropna(subset=[ground_truth_col]).index
    idx_to_pos = {idx: i for i, idx in enumerate(all_valid_idx)}
    
    valid_positions = []
    valid_gt = []
    for idx in common_idx:
        if idx in idx_to_pos:
            valid_positions.append(idx_to_pos[idx])
            valid_gt.append(gt_series[idx])
    
    if len(valid_positions) < 2:
        return None
    
    X_valid = X_encoded[valid_positions]
    gt_values = np.array(valid_gt)
    labels_valid = labels[valid_positions]
    
    le = LabelEncoder()
    gt_labels = le.fit_transform(gt_values.astype(str))
    
    n_gt = len(le.classes_)
    
    # PCA 降维
    if X_valid.shape[1] >= 2:
        pca = PCA(n_components=2)
        coords = pca.fit_transform(X_valid)
        var1, var2 = pca.explained_variance_ratio_[:2]
    else:
        coords = np.column_stack([X_valid[:, 0], np.zeros(len(X_valid))])
        var1, var2 = 1.0, 0.0
    
    fig = plt.figure(figsize=(18, 10))
    
    # 子图1：聚类结果 PCA 散点图
    ax1 = fig.add_subplot(2, 3, (1, 2))
    scatter = ax1.scatter(coords[:, 0], coords[:, 1],
                          c=labels_valid, cmap='viridis', alpha=0.6, s=40)
    ax1.set_xlabel(f'PC1 ({var1*100:.1f}%)')
    ax1.set_ylabel(f'PC2 ({var2*100:.1f}%)')
    ax1.set_title(f'{algorithm_name} 聚类结果 (PCA降维)', fontsize=12, fontweight='bold')
    plt.colorbar(scatter, ax=ax1, label='Cluster')
    
    # 子图2：实际分类散点图
    ax2 = fig.add_subplot(2, 3, 3)
    scatter2 = ax2.scatter(coords[:, 0], coords[:, 1],
                           c=gt_labels, cmap='Set3', alpha=0.6, s=40)
    ax2.set_xlabel(f'PC1 ({var1*100:.1f}%)')
    ax2.set_ylabel(f'PC2 ({var2*100:.1f}%)')
    ax2.set_title(f'实际值: {ground_truth_col}', fontsize=12, fontweight='bold')
    cbar2 = plt.colorbar(scatter2, ax=ax2)
    cbar2.set_ticks(range(n_gt))
    cbar2.set_ticklabels([str(x)[:15] for x in le.classes_])
    
    # 子图3：各簇中实际类别占比
    ax3 = fig.add_subplot(2, 3, 4)
    ct = pd.crosstab(labels_valid, gt_labels)
    ct_pct = ct.div(ct.sum(axis=1), axis=0)
    ct_pct.index = [f"簇 {i}" for i in ct_pct.index]
    ct_pct.columns = [str(x)[:12] for x in le.classes_]
    ct_pct.plot(kind='bar', stacked=True, ax=ax3, colormap='Set3', edgecolor='white')
    ax3.set_title('各簇中实际类别占比', fontsize=12, fontweight='bold')
    ax3.set_xlabel('聚类结果')
    ax3.set_ylabel('占比')
    ax3.legend(title=ground_truth_col, fontsize=7, title_fontsize=8, loc='upper right')
    ax3.set_xticklabels(ax3.get_xticklabels(), rotation=0)
    
    # 子图4：实际类别中各簇分布
    ax4 = fig.add_subplot(2, 3, 5)
    ct2 = pd.crosstab(gt_labels, labels_valid)
    ct2_pct = ct2.div(ct2.sum(axis=1), axis=0)
    ct2_pct.index = [str(x)[:12] for x in le.classes_]
    ct2_pct.columns = [f"簇 {i}" for i in ct2_pct.columns]
    ct2_pct.plot(kind='bar', stacked=True, ax=ax4, colormap='viridis', edgecolor='white')
    ax4.set_title('实际类别中各簇分布', fontsize=12, fontweight='bold')
    ax4.set_xlabel(ground_truth_col)
    ax4.set_ylabel('占比')
    ax4.legend(title='聚类', fontsize=7, title_fontsize=8, loc='upper right')
    ax4.set_xticklabels(ax4.get_xticklabels(), rotation=45, ha='right')
    
    # 子图5：各簇样本分布饼图
    ax5 = fig.add_subplot(2, 3, 6)
    cluster_counts = pd.Series(labels_valid).value_counts().sort_index()
    pie_labels = [f"簇 {i}" for i in cluster_counts.index]
    ax5.pie(cluster_counts.values, labels=pie_labels, autopct='%1.1f%%',
            startangle=90, colors=plt.cm.viridis(np.linspace(0, 1, len(cluster_counts))))
    ax5.set_title('各簇样本分布', fontsize=12, fontweight='bold')
    
    # 底部添加列信息
    fig.text(0.5, 0.01, f'原始列: {", ".join(list(data_subset.columns[:8]))}{"..." if len(data_subset.columns) > 8 else ""} | 编码后维度: {X_encoded.shape[1]}',
             ha='center', fontsize=7, color='gray', style='italic')
    
    plt.tight_layout(rect=[0, 0.03, 1, 1])
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=120, bbox_inches='tight')
    buf.seek(0)
    img_base64 = f"data:image/png;base64,{base64.b64encode(buf.read()).decode('utf-8')}"
    plt.close('all')
    
    return img_base64


# ==================== 聚类分析 ====================

def _do_clustering_kmeans(df, columns, n_clusters, ground_truth_col=''):
    """K-Means 聚类分析（支持混合类型列，通过 One-Hot 编码处理非数值列）"""
    if not columns:
        # 默认选择所有列（数值+非数值）
        all_cols = df.columns.tolist()
        columns = all_cols[:min(len(all_cols), 8)]
    else:
        columns = [c for c in columns if c in df.columns]
    
    if len(columns) < 1:
        return jsonify({"error": "请至少选择 1 个分析列"}), 400
    
    # 编码混合类型列
    try:
        X_encoded, encoded_col_names, preprocessor = _encode_mixed_columns(df, columns)
    except ValueError as e:
        return jsonify({"error": f"数据编码失败: {str(e)}"}), 400
    
    n_samples = X_encoded.shape[0]    # 数组行数（样本数）
    if n_samples < 2:
        return jsonify({"error": "有效样本数不足"}), 400
    
    kmeans = KMeans(n_clusters=n_clusters, random_state=42, n_init=10)
    labels = kmeans.fit_predict(X_encoded)
    
    # 内部评估指标
    sil_score = silhouette_score(X_encoded, labels) if len(set(labels)) > 1 else 0  # 轮廓系数
    inertia = float(kmeans.inertia_)    # 簇内平方和
    
    # 基于实际值的评估
    ground_truth_eval = _evaluate_with_ground_truth(labels, df, ground_truth_col, columns, n_samples)
    
    cluster_counts = pd.Series(labels).value_counts().sort_index().to_dict()
    cluster_counts = {f"簇 {k}": int(v) for k, v in cluster_counts.items()}
    
    # 构建结果 DataFrame（原始数据 + 聚类标签）
    data_original = df[columns].copy()
    # 对类别列的空值做填充后再展示
    for col in columns:
        if not pd.api.types.is_numeric_dtype(data_original[col]) and data_original[col].isna().any():
            mode_val = data_original[col].mode()
            fill_val = mode_val[0] if len(mode_val) > 0 else "未知"
            data_original[col] = data_original[col].fillna(fill_val)
    data_original = data_original.dropna()
    if len(data_original) == len(labels):
        data_original['Cluster'] = labels.astype(str)
    else:
        # 长度不一致时截断
        data_original = data_original.iloc[:len(labels)].copy()
        data_original['Cluster'] = labels.astype(str)
    
    # 可视化
    if ground_truth_col and ground_truth_col in df.columns:
        img_base64 = _build_ground_truth_chart_v2(X_encoded, labels, ground_truth_col, df, 'K-Means', encoded_col_names)
    else:
        img_base64 = _build_clustering_chart(X_encoded, labels, columns, encoded_col_names, n_clusters, 'K-Means', cluster_counts)
    
    result = {
        "type": "clustering",
        "algorithm": "K-Means",
        "n_clusters": n_clusters,
        "evaluation": {
            "silhouette_score": round(sil_score, 4),
            "inertia": round(inertia, 4),
        },
        "cluster_counts": cluster_counts,
        "columns_used": columns,
        "encoded_dimension": X_encoded.shape[1],
        "encoded_columns": encoded_col_names[:50],  # 限制返回数量
        "image": img_base64,
        "sample_data": df_to_json(data_original.head(100)),
    }
    
    if ground_truth_eval:
        result["ground_truth_evaluation"] = ground_truth_eval
    
    return jsonify(result)


def _do_clustering_dbscan(df, columns, ground_truth_col=''):
    """DBSCAN 聚类分析（支持混合类型列，通过 One-Hot 编码处理非数值列）"""
    if not columns:
        all_cols = df.columns.tolist()
        columns = all_cols[:min(len(all_cols), 8)]
    else:
        columns = [c for c in columns if c in df.columns]
    
    if len(columns) < 1:
        return jsonify({"error": "请至少选择 1 个分析列"}), 400
    
    # 编码混合类型列
    try:
        X_encoded, encoded_col_names, preprocessor = _encode_mixed_columns(df, columns)
    except ValueError as e:
        return jsonify({"error": f"数据编码失败: {str(e)}"}), 400
    
    n_samples = X_encoded.shape[0]
    if n_samples < 2:
        return jsonify({"error": "有效样本数不足"}), 400
    
    # 自适应 eps：使用最近邻距离的 80 百分位
    from sklearn.neighbors import NearestNeighbors
    nn = NearestNeighbors(n_neighbors=min(5, n_samples - 1))
    nn.fit(X_encoded)
    distances, _ = nn.kneighbors(X_encoded)
    eps = np.percentile(distances[:, -1], 80)
    eps = max(eps, 0.1)
    
    dbscan = DBSCAN(eps=eps, min_samples=5)
    labels = dbscan.fit_predict(X_encoded)
    
    n_clusters_found = len(set(labels)) - (1 if -1 in labels else 0)
    n_noise = int(np.sum(labels == -1))
    
    # 内部评估指标
    sil_score = 0
    if n_clusters_found >= 2:
        mask = labels != -1
        if np.sum(mask) > n_clusters_found:
            sil_score = silhouette_score(X_encoded[mask], labels[mask])
    elif n_clusters_found == 1:
        sil_score = -1
    
    # 基于实际值的评估
    if ground_truth_col and ground_truth_col in df.columns:
        ground_truth_eval = _evaluate_with_ground_truth(labels, df, ground_truth_col, columns, n_samples)
        if ground_truth_eval and n_noise > 0 and n_clusters_found >= 1:
            non_noise_mask = labels != -1
            if np.sum(non_noise_mask) >= 2:
                ground_truth_eval["evaluation_excluding_noise"] = {
                    "note": "以下评估排除了噪声点",
                    "noise_count": n_noise,
                    "non_noise_count": int(np.sum(non_noise_mask)),
                }
    else:
        ground_truth_eval = None
    
    cluster_counts = {}
    for lbl in sorted(set(labels)):
        count = int(np.sum(labels == lbl))
        if lbl == -1:
            cluster_counts["噪声点"] = count
        else:
            cluster_counts[f"簇 {lbl}"] = count
    
    # 构建结果 DataFrame
    data_original = df[columns].copy()
    for col in columns:
        if not pd.api.types.is_numeric_dtype(data_original[col]) and data_original[col].isna().any():
            mode_val = data_original[col].mode()
            fill_val = mode_val[0] if len(mode_val) > 0 else "未知"
            data_original[col] = data_original[col].fillna(fill_val)
    data_original = data_original.dropna()
    if len(data_original) == len(labels):
        data_original['Cluster'] = [f"簇{l}" if l != -1 else "噪声" for l in labels]
    else:
        data_original = data_original.iloc[:len(labels)].copy()
        data_original['Cluster'] = [f"簇{l}" if l != -1 else "噪声" for l in labels]
    
    # 可视化
    if ground_truth_col and ground_truth_col in df.columns:
        img_base64 = _build_ground_truth_chart_v2(X_encoded, labels, ground_truth_col, df, 'DBSCAN', encoded_col_names)
    else:
        img_base64 = _build_clustering_chart(X_encoded, labels, columns, encoded_col_names, n_clusters_found, 'DBSCAN', cluster_counts, eps=eps)
    
    result = {
        "type": "clustering",
        "algorithm": "DBSCAN",
        "n_clusters": n_clusters_found,
        "eps": round(eps, 4),
        "n_noise": n_noise,
        "evaluation": {
            "silhouette_score": round(sil_score, 4),
            "n_clusters_found": n_clusters_found,
            "noise_points": n_noise,
        },
        "cluster_counts": cluster_counts,
        "columns_used": columns,
        "encoded_dimension": X_encoded.shape[1],
        "encoded_columns": encoded_col_names[:50],
        "image": img_base64,
        "sample_data": df_to_json(data_original.head(100)),
    }
    
    if ground_truth_eval:
        result["ground_truth_evaluation"] = ground_truth_eval
    
    return jsonify(result)
