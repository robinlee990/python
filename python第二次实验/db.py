# ============================================================
# 数据库模块 - MySQL 持久化存储
# 表：users / files / data_rows / cleaning_logs / analysis_results
# 使用 PyMySQL 驱动
# ============================================================

import json
import os
import hashlib

import numpy as np
import pandas as pd
import pymysql


def pd_is_na(val):
    """安全判断 pandas NA"""
    try:
        return pd.isna(val)
    except Exception:
        return val is None

# ==================== MySQL 连接配置（请改成你自己 MySQL 的信息） ====================
DB_CONFIG = {
    'host': '10.77.195.183',
    'port': 3306,
    'user': 'data_user',
    'password': 'Root@123456',
    'database': 'data_system',
    'charset': 'utf8mb4',
    'cursorclass': pymysql.cursors.DictCursor,
    'autocommit': False,
}


def get_db():
    """获取 MySQL 数据库连接"""
    return pymysql.connect(**DB_CONFIG)


def init_db():
    """初始化数据库表结构"""
    conn = get_db()
    cursor = conn.cursor()

    # ========== 用户表 ==========
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            username    VARCHAR(100) UNIQUE NOT NULL,
            password    VARCHAR(255) NOT NULL,
            nickname    VARCHAR(100) DEFAULT '',
            role        VARCHAR(20)  DEFAULT 'user',
            created_at  TIMESTAMP    DEFAULT CURRENT_TIMESTAMP
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')

    # ========== 上传文件元数据表 ==========
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS files (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            user_id         INT NOT NULL,
            filename        VARCHAR(255) NOT NULL,
            original_name   VARCHAR(255) NOT NULL,
            file_size       INT DEFAULT 0,
            file_path       VARCHAR(500) DEFAULT '',
            row_count       INT DEFAULT 0,
            col_count       INT DEFAULT 0,
            columns_info    JSON DEFAULT NULL,
            status          VARCHAR(50)  DEFAULT 'uploaded',
            uploaded_at     TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')

    # ========== 数据行表 ==========
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS data_rows (
            id          INT AUTO_INCREMENT PRIMARY KEY,
            file_id     INT NOT NULL,
            row_index   INT NOT NULL,
            row_data    JSON NOT NULL,
            is_valid    TINYINT DEFAULT 1,
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')

    # 索引（忽略已存在错误）
    try:
        cursor.execute('CREATE INDEX idx_data_rows_file ON data_rows(file_id, is_valid)')
    except pymysql.err.OperationalError:
        pass

    # ========== 清洗日志表 ==========
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS cleaning_logs (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            file_id         INT NOT NULL,
            user_id         INT NOT NULL,
            operation       JSON DEFAULT NULL,
            missing_before  INT DEFAULT 0,
            missing_after   INT DEFAULT 0,
            outliers_found  INT DEFAULT 0,
            rows_before     INT DEFAULT 0,
            rows_after      INT DEFAULT 0,
            params_json     JSON DEFAULT NULL,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')

    # ========== 分析结果表 ==========
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS analysis_results (
            id              INT AUTO_INCREMENT PRIMARY KEY,
            file_id         INT NOT NULL,
            user_id         INT NOT NULL,
            analysis_type   VARCHAR(50) NOT NULL,
            parameters      JSON DEFAULT NULL,
            result_data     JSON DEFAULT NULL,
            image_base64    LONGTEXT,
            created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    ''')

    conn.commit()

    # 创建默认管理员账号
    cursor.execute("SELECT id FROM users WHERE username = %s", ("admin",))
    existing = cursor.fetchone()
    if not existing:
        pwd = hashlib.sha256("admin123".encode()).hexdigest()
        cursor.execute(
            "INSERT INTO users (username, password, nickname, role) VALUES (%s, %s, %s, %s)",
            ("admin", pwd, "系统管理员", "admin")
        )
        conn.commit()

    conn.close()
    print("[DB] MySQL 数据库初始化完成")


# ==================== 用户操作 ====================

def create_user(username, password, nickname=''):
    """注册新用户"""
    conn = get_db()
    try:
        pwd_hash = hashlib.sha256(password.encode()).hexdigest()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO users (username, password, nickname) VALUES (%s, %s, %s)",
            (username, pwd_hash, nickname or username)
        )
        conn.commit()
        return True, "注册成功"
    except pymysql.err.IntegrityError:
        conn.rollback()
        return False, "用户名已存在"
    finally:
        conn.close()


def verify_user(username, password):
    """验证用户登录"""
    conn = get_db()
    cursor = conn.cursor()
    pwd_hash = hashlib.sha256(password.encode()).hexdigest()
    cursor.execute(
        "SELECT id, username, nickname, role FROM users WHERE username=%s AND password=%s",
        (username, pwd_hash)
    )
    row = cursor.fetchone()
    conn.close()
    return row


def get_user_by_id(user_id):
    """根据 ID 获取用户信息"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, nickname, role FROM users WHERE id=%s", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row


def get_all_users():
    """获取所有用户列表"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, username, nickname, role, created_at FROM users ORDER BY id")
    rows = cursor.fetchall()
    conn.close()
    return rows


# ==================== 文件管理 ====================

def insert_file(user_id, filename, original_name, file_size, file_path,
                row_count, col_count, columns_info):
    """插入文件记录，返回 file_id"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO files (user_id, filename, original_name, file_size, file_path,
           row_count, col_count, columns_info, status)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'uploaded')""",
        (user_id, filename, original_name, file_size, file_path,
         row_count, col_count, json.dumps(columns_info, ensure_ascii=False))
    )
    conn.commit()
    file_id = cursor.lastrowid
    conn.close()
    return file_id


def get_user_files(user_id):
    """获取某用户的所有上传文件"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT f.*, u.username
           FROM files f JOIN users u ON f.user_id = u.id
           WHERE f.user_id = %s
           ORDER BY f.uploaded_at DESC""",
        (user_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    for d in rows:
        if isinstance(d.get('columns_info'), str):
            d['columns_info'] = json.loads(d['columns_info'])
    return rows


def get_all_files():
    """获取所有文件（管理员用）"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT f.*, u.username
           FROM files f JOIN users u ON f.user_id = u.id
           ORDER BY f.uploaded_at DESC"""
    )
    rows = cursor.fetchall()
    conn.close()
    for d in rows:
        if isinstance(d.get('columns_info'), str):
            d['columns_info'] = json.loads(d['columns_info'])
    return rows


def get_file_by_id(file_id):
    """获取单个文件信息"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT f.*, u.username
           FROM files f JOIN users u ON f.user_id = u.id
           WHERE f.id = %s""", (file_id,)
    )
    row = cursor.fetchone()
    conn.close()
    if row:
        if isinstance(row.get('columns_info'), str):
            row['columns_info'] = json.loads(row['columns_info'])
        return row
    return None


def update_file_status(file_id, status, row_count=None, col_count=None, columns_info=None):
    """更新文件状态"""
    conn = get_db()
    cursor = conn.cursor()
    sql_parts = ["status = %s"]
    params = [status]
    if row_count is not None:
        sql_parts.append("row_count = %s")
        params.append(row_count)
    if col_count is not None:
        sql_parts.append("col_count = %s")
        params.append(col_count)
    if columns_info is not None:
        sql_parts.append("columns_info = %s")
        params.append(json.dumps(columns_info, ensure_ascii=False))
    params.append(file_id)
    cursor.execute(f"UPDATE files SET {', '.join(sql_parts)} WHERE id = %s", params)
    conn.commit()
    conn.close()


def delete_file(file_id):
    """删除文件及其所有关联数据"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM analysis_results WHERE file_id = %s", (file_id,))
    cursor.execute("DELETE FROM cleaning_logs WHERE file_id = %s", (file_id,))
    cursor.execute("DELETE FROM data_rows WHERE file_id = %s", (file_id,))
    cursor.execute("SELECT file_path FROM files WHERE id = %s", (file_id,))
    row = cursor.fetchone()
    if row and row['file_path'] and os.path.exists(row['file_path']):
        os.remove(row['file_path'])
    cursor.execute("DELETE FROM files WHERE id = %s", (file_id,))
    conn.commit()
    conn.close()


# ==================== 数据行操作 ====================

def insert_data_rows(file_id, df):
    """将 DataFrame 逐行存入 data_rows（批量插入）"""
    conn = get_db()
    cursor = conn.cursor()
    rows_data = []
    for idx, row in df.iterrows():
        row_dict = row.to_dict()
        for k, v in row_dict.items():
            if pd_is_na(v):
                row_dict[k] = None
            elif isinstance(v, (np.integer,)):
                row_dict[k] = int(v)
            elif isinstance(v, (np.floating,)):
                row_dict[k] = float(v)
            elif isinstance(v, (np.bool_,)):
                row_dict[k] = bool(v)
        rows_data.append((file_id, idx, json.dumps(row_dict, ensure_ascii=False), 1))

    cursor.executemany(
        "INSERT INTO data_rows (file_id, row_index, row_data, is_valid) VALUES (%s, %s, %s, %s)",
        rows_data
    )
    conn.commit()
    conn.close()


def clear_data_rows(file_id):
    """清空某文件的数据行"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM data_rows WHERE file_id = %s", (file_id,))
    conn.commit()
    conn.close()


def get_data_as_df(file_id, valid_only=True):
    """从 data_rows 读取数据并还原为 DataFrame"""
    conn = get_db()
    cursor = conn.cursor()
    file_info = get_file_by_id(file_id)
    if not file_info or not file_info.get('columns_info'):
        conn.close()
        return None, []

    columns_info = file_info['columns_info']
    col_names = [c['name'] for c in columns_info]

    if valid_only:
        cursor.execute(
            "SELECT row_data FROM data_rows WHERE file_id = %s AND is_valid = 1 ORDER BY row_index",
            (file_id,)
        )
    else:
        cursor.execute(
            "SELECT row_data FROM data_rows WHERE file_id = %s ORDER BY row_index",
            (file_id,)
        )
    rows = cursor.fetchall()
    conn.close()

    data = []
    for r in rows:
        row_data = r['row_data']
        if isinstance(row_data, str):
            row_data = json.loads(row_data)
        data.append(row_data)

    df = pd.DataFrame(data, columns=col_names) if data else pd.DataFrame(columns=col_names)

    for col_info in columns_info:
        name = col_info['name']
        if name in df.columns and col_info.get('type') == 'numeric':
            df[name] = pd.to_numeric(df[name], errors='coerce')

    return df, columns_info


def update_data_rows_after_clean(file_id, df):
    """清洗后更新数据行"""
    clear_data_rows(file_id)
    insert_data_rows(file_id, df)
    update_file_status(file_id, 'cleaned', row_count=len(df), col_count=len(df.columns))


def reset_data_rows(file_id, df):
    """重置数据到原始状态"""
    clear_data_rows(file_id)
    insert_data_rows(file_id, df)
    update_file_status(file_id, 'uploaded', row_count=len(df), col_count=len(df.columns))


# ==================== 清洗日志 ====================

def insert_cleaning_log(file_id, user_id, operation_logs, missing_before, missing_after,
                        outliers_found, rows_before, rows_after, params_json):
    """插入清洗日志"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO cleaning_logs
           (file_id, user_id, operation, missing_before, missing_after,
            outliers_found, rows_before, rows_after, params_json)
           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
        (file_id, user_id, json.dumps(operation_logs, ensure_ascii=False),
         missing_before, missing_after, outliers_found, rows_before, rows_after,
         json.dumps(params_json, ensure_ascii=False))
    )
    conn.commit()
    conn.close()


def get_cleaning_logs(file_id):
    """获取某文件的清洗历史"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT cl.*, u.username
           FROM cleaning_logs cl JOIN users u ON cl.user_id = u.id
           WHERE cl.file_id = %s
           ORDER BY cl.created_at DESC""",
        (file_id,)
    )
    rows = cursor.fetchall()
    conn.close()
    for d in rows:
        if isinstance(d.get('operation'), str):
            d['operation'] = json.loads(d['operation'])
        if isinstance(d.get('params_json'), str):
            d['params_json'] = json.loads(d['params_json'])
    return rows


# ==================== 分析结果 ====================

def insert_analysis_result(file_id, user_id, analysis_type, parameters, result_data, image_base64=''):
    """保存分析结果"""
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO analysis_results
           (file_id, user_id, analysis_type, parameters, result_data, image_base64)
           VALUES (%s, %s, %s, %s, %s, %s)""",
        (file_id, user_id, analysis_type,
         json.dumps(parameters, ensure_ascii=False),
         json.dumps(result_data, ensure_ascii=False) if isinstance(result_data, dict) else result_data,
         image_base64)
    )
    conn.commit()
    conn.close()


def get_analysis_results(file_id, analysis_type=None):
    """获取分析历史"""
    conn = get_db()
    cursor = conn.cursor()
    if analysis_type:
        cursor.execute(
            """SELECT ar.*, u.username
               FROM analysis_results ar JOIN users u ON ar.user_id = u.id
               WHERE ar.file_id = %s AND ar.analysis_type = %s
               ORDER BY ar.created_at DESC""",
            (file_id, analysis_type)
        )
    else:
        cursor.execute(
            """SELECT ar.*, u.username
               FROM analysis_results ar JOIN users u ON ar.user_id = u.id
               WHERE ar.file_id = %s
               ORDER BY ar.created_at DESC""",
            (file_id,)
        )
    rows = cursor.fetchall()
    conn.close()
    for d in rows:
        if isinstance(d.get('parameters'), str):
            d['parameters'] = json.loads(d['parameters'])
        if d['analysis_type'] in ['clustering', 'regression', 'pca']:
            try:
                d['result_data'] = json.loads(d['result_data']) if isinstance(d['result_data'], str) else d['result_data']
            except:
                pass
    return rows

# ==================== 管理员检索功能 ====================

def search_users(keyword='', role='', date_from='', date_to='', page=1, per_page=20):
    """
    管理员检索用户
    支持：用户名/昵称关键字、角色筛选、注册时间范围、分页
    """
    conn = get_db()
    cursor = conn.cursor()

    conditions = []
    params = []

    if keyword:
        conditions.append("(username LIKE %s OR nickname LIKE %s)")
        params.extend([f'%{keyword}%', f'%{keyword}%'])
    if role:
        conditions.append("role = %s")
        params.append(role)
    if date_from:
        conditions.append("DATE(created_at) >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("DATE(created_at) <= %s")
        params.append(date_to)

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # 总数
    cursor.execute(f"SELECT COUNT(*) as cnt FROM users {where_sql}", params)
    total = cursor.fetchone()['cnt']

    # 分页数据
    offset = (page - 1) * per_page
    cursor.execute(
        f"""SELECT id, username, nickname, role, created_at
            FROM users {where_sql}
            ORDER BY created_at DESC
            LIMIT %s OFFSET %s""",
        params + [per_page, offset]
    )
    rows = cursor.fetchall()
    conn.close()

    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


def search_files(keyword='', username='', status='', date_from='', date_to='',
                 min_rows=None, max_rows=None, page=1, per_page=20):
    """
    管理员检索文件
    支持：文件名关键字、上传用户名、清洗状态、上传时间范围、行数范围、分页
    """
    conn = get_db()
    cursor = conn.cursor()

    conditions = []
    params = []

    if keyword:
        conditions.append("(f.original_name LIKE %s OR f.filename LIKE %s)")
        params.extend([f'%{keyword}%', f'%{keyword}%'])
    if username:
        conditions.append("u.username LIKE %s")
        params.append(f'%{username}%')
    if status:
        conditions.append("f.status = %s")
        params.append(status)
    if date_from:
        conditions.append("DATE(f.uploaded_at) >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("DATE(f.uploaded_at) <= %s")
        params.append(date_to)
    if min_rows is not None:
        conditions.append("f.row_count >= %s")
        params.append(int(min_rows))
    if max_rows is not None:
        conditions.append("f.row_count <= %s")
        params.append(int(max_rows))

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    cursor.execute(
        f"""SELECT COUNT(*) as cnt
            FROM files f JOIN users u ON f.user_id = u.id
            {where_sql}""",
        params
    )
    total = cursor.fetchone()['cnt']

    offset = (page - 1) * per_page
    cursor.execute(
        f"""SELECT f.id, f.original_name, f.filename, f.file_size,
                   f.row_count, f.col_count, f.status, f.uploaded_at,
                   u.id as user_id, u.username
            FROM files f JOIN users u ON f.user_id = u.id
            {where_sql}
            ORDER BY f.uploaded_at DESC
            LIMIT %s OFFSET %s""",
        params + [per_page, offset]
    )
    rows = cursor.fetchall()
    conn.close()

    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


def search_cleaning_logs(keyword='', username='', date_from='', date_to='',
                         page=1, per_page=20):
    """
    管理员检索清洗日志
    支持：文件名关键字、操作用户名、时间范围、分页
    """
    conn = get_db()
    cursor = conn.cursor()

    conditions = []
    params = []

    if keyword:
        conditions.append("f.original_name LIKE %s")
        params.append(f'%{keyword}%')
    if username:
        conditions.append("u.username LIKE %s")
        params.append(f'%{username}%')
    if date_from:
        conditions.append("DATE(cl.created_at) >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("DATE(cl.created_at) <= %s")
        params.append(date_to)

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    cursor.execute(
        f"""SELECT COUNT(*) as cnt
            FROM cleaning_logs cl
            JOIN users u ON cl.user_id = u.id
            JOIN files f ON cl.file_id = f.id
            {where_sql}""",
        params
    )
    total = cursor.fetchone()['cnt']

    offset = (page - 1) * per_page
    cursor.execute(
        f"""SELECT cl.id, cl.file_id, cl.missing_before, cl.missing_after,
                   cl.outliers_found, cl.rows_before, cl.rows_after,
                   cl.operation, cl.created_at,
                   u.username, f.original_name as filename
            FROM cleaning_logs cl
            JOIN users u ON cl.user_id = u.id
            JOIN files f ON cl.file_id = f.id
            {where_sql}
            ORDER BY cl.created_at DESC
            LIMIT %s OFFSET %s""",
        params + [per_page, offset]
    )
    rows = cursor.fetchall()
    conn.close()

    for d in rows:
        if isinstance(d.get('operation'), str):
            try:
                d['operation'] = json.loads(d['operation'])
            except Exception:
                pass

    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


def search_analysis_results(keyword='', username='', analysis_type='',
                            date_from='', date_to='', page=1, per_page=20):
    """
    管理员检索分析记录
    支持：文件名关键字、操作用户名、分析类型、时间范围、分页
    """
    conn = get_db()
    cursor = conn.cursor()

    conditions = []
    params = []

    if keyword:
        conditions.append("f.original_name LIKE %s")
        params.append(f'%{keyword}%')
    if username:
        conditions.append("u.username LIKE %s")
        params.append(f'%{username}%')
    if analysis_type:
        conditions.append("ar.analysis_type = %s")
        params.append(analysis_type)
    if date_from:
        conditions.append("DATE(ar.created_at) >= %s")
        params.append(date_from)
    if date_to:
        conditions.append("DATE(ar.created_at) <= %s")
        params.append(date_to)

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    cursor.execute(
        f"""SELECT COUNT(*) as cnt
            FROM analysis_results ar
            JOIN users u ON ar.user_id = u.id
            JOIN files f ON ar.file_id = f.id
            {where_sql}""",
        params
    )
    total = cursor.fetchone()['cnt']

    offset = (page - 1) * per_page
    cursor.execute(
        f"""SELECT ar.id, ar.file_id, ar.analysis_type, ar.parameters,
                   ar.created_at, u.username, f.original_name as filename
            FROM analysis_results ar
            JOIN users u ON ar.user_id = u.id
            JOIN files f ON ar.file_id = f.id
            {where_sql}
            ORDER BY ar.created_at DESC
            LIMIT %s OFFSET %s""",
        params + [per_page, offset]
    )
    rows = cursor.fetchall()
    conn.close()

    for d in rows:
        if isinstance(d.get('parameters'), str):
            try:
                d['parameters'] = json.loads(d['parameters'])
            except Exception:
                pass

    return {
        "items": rows,
        "total": total,
        "page": page,
        "per_page": per_page,
        "total_pages": max(1, (total + per_page - 1) // per_page),
    }


def get_admin_stats():
    """管理员全局统计概览"""
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as cnt FROM users")
    total_users = cursor.fetchone()['cnt']

    cursor.execute("SELECT COUNT(*) as cnt FROM users WHERE role = 'admin'")
    total_admins = cursor.fetchone()['cnt']

    cursor.execute("SELECT COUNT(*) as cnt FROM files")
    total_files = cursor.fetchone()['cnt']

    cursor.execute("SELECT COUNT(*) as cnt FROM files WHERE status = 'cleaned'")
    cleaned_files = cursor.fetchone()['cnt']

    cursor.execute("SELECT COUNT(*) as cnt FROM cleaning_logs")
    total_cleans = cursor.fetchone()['cnt']

    cursor.execute("SELECT COUNT(*) as cnt FROM analysis_results")
    total_analyses = cursor.fetchone()['cnt']

    cursor.execute(
        "SELECT analysis_type, COUNT(*) as cnt FROM analysis_results GROUP BY analysis_type"
    )
    analysis_by_type = {r['analysis_type']: r['cnt'] for r in cursor.fetchall()}

    cursor.execute(
        """SELECT u.username, COUNT(f.id) as file_count
           FROM users u LEFT JOIN files f ON u.id = f.user_id
           GROUP BY u.id, u.username
           ORDER BY file_count DESC LIMIT 5"""
    )
    top_users = cursor.fetchall()

    conn.close()

    return {
        "total_users": total_users,
        "total_admins": total_admins,
        "total_files": total_files,
        "cleaned_files": cleaned_files,
        "total_cleans": total_cleans,
        "total_analyses": total_analyses,
        "analysis_by_type": analysis_by_type,
        "top_users_by_files": top_users,
    }

# ---- 首次导入时自动初始化 ----
if __name__ != '__main__':
    init_db()
