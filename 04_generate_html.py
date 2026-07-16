"""
阶段 4: 生成指数增强基金排名 HTML 页面

读取 03_calculate_return.py 输出的 excess_return.parquet，
展示基金代码、基金简称、指数名称、日/月/年涨跌幅、日/月/年超额。
"""

import os
import pandas as pd

from config import EXCESS_RETURN_PATH


OUTPUT_HTML = "output/index.html"


# ── 各周期对应的"成立不足X"说明 ──
# 按周期从长到短排列：如果长周期为空，检查次短周期是否有数据
PERIOD_HIERARCHY = [
    ("year_1_change",  "month_6_change",  "成立不足1年"),
    ("month_6_change", "month_1_change",  "成立不足6月"),
    ("month_1_change", "daily_change",    "成立不足1月"),
    ("daily_change",   None,              "无数据"),
]
# 超额列同理
PERIOD_HIERARCHY_EXCESS = [
    ("year_1_excess",  "month_6_excess",  "成立不足1年"),
    ("month_6_excess", "month_1_excess",  "成立不足6月"),
    ("month_1_excess", "daily_excess",    "成立不足1月"),
    ("daily_excess",   None,              "无数据"),
]


def _get_empty_reason(col: str, row: pd.Series) -> str:
    """根据该行其他周期的数据完整度，推断当前列为空的原因"""
    # 先查涨跌幅层级
    for target, shorter, reason in PERIOD_HIERARCHY:
        if col == target:
            if shorter is None:
                return reason
            if pd.notna(row.get(shorter)):
                return reason
            # 继续往下查（shorter 列也为空，看更短的周期）
            continue
    # 再查超额层级
    for target, shorter, reason in PERIOD_HIERARCHY_EXCESS:
        if col == target:
            if shorter is None:
                return reason
            if pd.notna(row.get(shorter)):
                return reason
            continue
    return "暂无数据"


def format_pct(x):
    """百分比格式化，保留两位小数，正数带 + 号"""
    if pd.isna(x):
        return None  # 返回 None，后续由 _format_cell 统一处理
    return f"{x * 100:+.2f}%"


def _format_cell(val, col_name, row):
    """格式化单元格：有值则返回百分比字符串，无值则返回原因说明"""
    if isinstance(val, str):
        return val
    return _get_empty_reason(col_name, row)


def load_data():
    if not os.path.exists(EXCESS_RETURN_PATH):
        print(f"[ERROR] 没有找到超额收益文件: {EXCESS_RETURN_PATH}")
        return pd.DataFrame()

    df = pd.read_parquet(EXCESS_RETURN_PATH)
    print(f"读取基金数据: {len(df)} 条")
    return df


# 列名 → 表头中文映射
COLUMN_LABELS = {
    "fund_code": "基金代码",
    "fund_name": "基金简称",
    "benchmark_name": "指数名称",
    "daily_change": "日涨跌幅",
    "month_1_change": "月涨跌幅",
    "year_1_change": "年涨跌幅",
    "daily_excess": "日超额",
    "month_1_excess": "月超额",
    "year_1_excess": "年超额",
}

# 数值列（需要格式化的）
PCT_COLUMNS = [
    "daily_change", "month_1_change", "year_1_change",
    "daily_excess", "month_1_excess", "year_1_excess",
]

# 保留用于推断空值原因的辅助列（不会显示在最终表格）
_AUX_COLUMNS = ["month_6_change", "month_6_excess"]


def prepare_table(df):
    """筛选最新日期、排序、格式化（空值标注原因）"""

    latest = df["date"].max()
    df = df[df["date"] == latest].copy()

    # 按基金代码升序排列
    df = df.sort_values("fund_code", ascending=True)

    columns = [
        "fund_code",
        "fund_name",
        "benchmark_name",
        "daily_change",
        "month_1_change",
        "year_1_change",
        "daily_excess",
        "month_1_excess",
        "year_1_excess",
    ]

    # 保留辅助列用于推断空值原因
    aux = [c for c in _AUX_COLUMNS if c in df.columns]
    df = df[[c for c in columns + aux if c in df.columns]]

    # 先对数值列做百分比格式化（NaN → None）
    for c in PCT_COLUMNS:
        if c in df.columns:
            df[c] = df[c].apply(format_pct)

    # 空值替换为原因说明
    for c in PCT_COLUMNS:
        if c in df.columns:
            df[c] = df.apply(lambda row: _format_cell(row[c], c, row), axis=1)

    # 去掉辅助列
    df = df[[c for c in columns if c in df.columns]]

    return df, latest


def generate_html(df, latest_date):
    os.makedirs(os.path.dirname(OUTPUT_HTML), exist_ok=True)

    date_str = str(latest_date)
    labels = COLUMN_LABELS.copy()
    labels["daily_change"] = f"日涨跌幅({date_str})"

    display_df = df.rename(columns=labels)

    # 统计空值情况（用于终端输出）
    empty_counts = {}
    for key in ["year_1_change", "month_1_change", "daily_change"]:
        col_label = labels.get(key, key)
        if col_label not in display_df.columns:
            continue
        non_pct = display_df[col_label].apply(
            lambda x: x if isinstance(x, str) and not x.endswith("%") else pd.NA
        )
        non_pct = non_pct.dropna()
        if len(non_pct) > 0:
            empty_counts[col_label] = len(non_pct)

    empty_note = ""
    if empty_counts:
        empty_note = '<div class="footnote"><p>说明：部分基金因成立时间不足，对应周期涨跌幅/超额为空，已在格内标注原因（如"成立不足1年"）。</p></div>'
        print()

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>指数增强基金排名</title>
<style>
    body {{
        font-family: "Microsoft YaHei", "PingFang SC", Arial, sans-serif;
        margin: 40px;
        background: #f8f9fa;
        color: #333;
    }}
    table {{
        border-collapse: collapse;
        width: 100%;
        background: #fff;
        box-shadow: 0 2px 8px rgba(0,0,0,0.08);
        border-radius: 4px;
        overflow: hidden;
    }}
    th {{
        background: #2c3e50;
        color: #fff;
        padding: 12px 10px;
        font-size: 14px;
        white-space: nowrap;
        position: sticky;
        top: 0;
        z-index: 10;
    }}
    td {{
        border-bottom: 1px solid #eef0f2;
        padding: 10px;
        text-align: center;
        font-size: 14px;
    }}
    tr:hover {{
        background: #f0f4f8;
    }}
    tr:nth-child(even) {{
        background: #fafbfc;
    }}
    tr:nth-child(even):hover {{
        background: #f0f4f8;
    }}
    td:not(:first-child):not(:nth-child(2)):not(:nth-child(3)) {{
        font-variant-numeric: tabular-nums;
    }}
    .empty-reason {{
        color: #999;
        font-size: 12px;
    }}
    .footnote {{
        margin-top: 20px;
        color: #888;
        font-size: 13px;
    }}
</style>
</head>
<body>
{display_df.to_html(index=False, escape=False, classes="fund-table")}
{empty_note}
</body>
</html>
"""

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    # 打印空值统计
    if empty_counts:
        print("  空值标注统计:")
        for col_label, count in empty_counts.items():
            print(f"    {col_label}: {count} 只")

    print(f"[OK] HTML 已生成: {OUTPUT_HTML}")


def main():
    print("=" * 60)
    print("Step 4  生成基金网页")
    print("=" * 60)

    df = load_data()
    if df.empty:
        return

    table, latest_date = prepare_table(df)
    generate_html(table, latest_date)

    print("\n完成!")


if __name__ == "__main__":
    main()
