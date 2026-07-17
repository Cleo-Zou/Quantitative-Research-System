"""
公共工具函数
被 01_build_fund_pool1.py / 02_update_nav.py / 03_calculate_return.py 共用
"""

import os
from datetime import date, timedelta

import pandas as pd


# ── 列名模糊匹配 ──

def find_col(df: pd.DataFrame, *candidates: str) -> str | None:
    """在 DataFrame 列名中模糊匹配，返回第一个包含任一候选字符串的列名"""
    for col in df.columns:
        col_str = str(col)
        for c in candidates:
            if c in col_str:
                return col
    return None


# ── 时间格式化 ──

def format_seconds(sec: float) -> str:
    """秒数 → 可读字符串（如 3min12s / 45s）"""
    if sec < 60:
        return f"{sec:.0f}s"
    m, s = divmod(int(sec), 60)
    return f"{m}min{s}s"


# ── 最近交易日（工作日近似） ──

def get_last_business_day() -> date:
    """返回最近一个工作日。

    不处理节假日，仅跳过周末。
    未来可替换为 AKShare / Tushare 交易日历，接口不变。
    """
    today = date.today()
    if today.weekday() == 5:       # 周六 → 周五
        return today - timedelta(days=1)
    if today.weekday() == 6:       # 周日 → 周五
        return today - timedelta(days=2)
    return today


# ── 安全的 parquet 读写 ──

def safe_read_parquet(path: str) -> pd.DataFrame | None:
    """读取 parquet 文件，文件不存在或损坏时返回 None"""
    if not os.path.exists(path):
        return None
    try:
        return pd.read_parquet(path)
    except Exception:
        return None


def safe_write_parquet(df: pd.DataFrame, path: str):
    """写入 parquet 文件，自动创建父目录"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    df.to_parquet(path, index=False)
