# ============================================================
# 模块 3: 可视化模块 (visualizer.py)
# 功能：动态生成多种图表（柱状图/折线图/散点图/饼图/直方图/箱线图/热力图/相关性矩阵）
# ============================================================

import os
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns

sns.set(style="whitegrid")

# CSV 文件夹路径
UPLOADS_DIR = "uploads"

def generate_charts(df, file_name):
    """为单个 DataFrame 生成所有图表"""

    # =========================
    # 1. 柱状图：行业分布
    # =========================
    try:
        if 'industry' in df.columns:
            plt.figure(figsize=(8, 5))
            df['industry'].value_counts().head(10).plot(kind='bar', color='skyblue')
            plt.title("Top 10 Industries")
            plt.xlabel("Industry")
            plt.ylabel("Count")
            plt.xticks(rotation=45)
            plt.tight_layout()
            plt.savefig(f"{file_name}_bar_chart.png")
            plt.close()
            print("柱状图生成成功")
    except Exception as e:
        print(f"柱状图生成失败: {file_name}\n{e}")

    # =========================
    # 2. 折线图：压力水平趋势
    # =========================
    try:
        if 'year' in df.columns and 'stress_level' in df.columns:
            # 确保数值类型
            if pd.api.types.is_numeric_dtype(df['stress_level']):
                plt.figure(figsize=(8, 5))
                df.groupby('year')['stress_level'].mean().plot(kind='line', marker='o')
                plt.title("Stress Level Trend")
                plt.xlabel("Year")
                plt.ylabel("Average Stress Level")
                plt.tight_layout()
                plt.savefig(f"{file_name}_line_chart.png")
                plt.close()
                print("折线图生成成功")
            else:
                print(f"折线图字段不是数值: {file_name}")
    except Exception as e:
        print(f"折线图生成失败: {file_name}\n{e}")

    # =========================
    # 3. 饼图：性别分布
    # =========================
    try:
        if 'gender' in df.columns:
            plt.figure(figsize=(6, 6))
            df['gender'].value_counts().plot(kind='pie', autopct='%1.1f%%', startangle=90)
            plt.title("Gender Distribution")
            plt.ylabel("")
            plt.tight_layout()
            plt.savefig(f"{file_name}_pie_chart.png")
            plt.close()
            print("饼图生成成功")
    except Exception as e:
        print(f"饼图生成失败: {file_name}\n{e}")

    # =========================
    # 4. 热力图：数值字段相关性
    # =========================
    try:
        numeric_df = df.select_dtypes(include=['number'])
        if not numeric_df.empty:
            corr = numeric_df.corr()
            plt.figure(figsize=(10, 8))
            sns.heatmap(corr, cmap='coolwarm', annot=False)
            plt.title("Correlation Heatmap")
            plt.tight_layout()
            plt.savefig(f"{file_name}_heatmap.png")
            plt.close()
            print("热力图生成成功")
        else:
            print(f"没有数值字段可生成热力图: {file_name}")
    except Exception as e:
        print(f"热力图生成失败: {file_name}\n{e}")


def main():
    for file_name in os.listdir(UPLOADS_DIR):
        if file_name.endswith(".csv"):
            file_path = os.path.join(UPLOADS_DIR, file_name)
            print(f"正在处理文件: {file_name}")
            try:
                df = pd.read_csv(file_path)
                print(df.head())
                generate_charts(df, file_name.split(".")[0])
            except Exception as e:
                print(f"读取 CSV 失败: {file_name}\n{e}")

    print("全部图表生成完成！")


if __name__ == "__main__":
    main()