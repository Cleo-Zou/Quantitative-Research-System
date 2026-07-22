"""
Excel 格式化导出

Sheet 结构（每 Benchmark 一个 + 汇总概览）:
    五核心指标 | Alpha | Profile | Tags | 五段摘要
"""

import os
import time
import pandas as pd
from config import INDEX_NAMES

# ── Excel 列定义 ──
# (内部列名, 表头, 列宽)

SHEET_COLUMNS = [
    # 基础信息
    ("fund_code",         "基金代码",    12),
    ("fund_name",         "基金简称",    28),
    ("benchmark_name",    "指数名称",    12),
    # 五核心指标
    ("annual_return",     "年化收益",    10),
    ("annual_volatility", "年化波动率",  10),
    ("sharpe_ratio",      "Sharpe",      10),
    ("max_drawdown",      "最大回撤",    10),
    ("calmar_ratio",      "Calmar",      10),
    # Alpha（短期→长期）
    ("month_1_alpha",     "1月超额",     10),
    ("month_6_alpha",     "6月超额",     10),
    ("year_1_alpha",      "年化超额",    10),
    # 研究解读
    ("profile",           "基金画像",    14),
    ("tags",              "研究标签",    36),
    ("return_summary",    "收益能力",    52),
    ("risk_summary",      "风险控制",    48),
    ("risk_adj_summary",  "风险调整收益", 42),
    ("consistency_summary","超额持续性",  46),
    ("summary_comment",   "综合画像",    40),
]

# 百分比格式的列
PCT_COLS = {"年化收益", "年化波动率", "最大回撤", "年化超额", "6月超额", "1月超额"}
# 数值格式的列（保留 2 位小数）
NUM_COLS = {"Sharpe", "Calmar"}


def export_excel(df: pd.DataFrame, output_path: str):
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # 构建列映射（仅保留 df 中实际存在的列）
    available = [(k, v, w) for k, v, w in SHEET_COLUMNS if k in df.columns]
    col_keys = [k for k, _, _ in available]
    col_names = [v for _, v, _ in available]

    # 排序
    idx_order = {"HS300": 0, "ZZ500": 1, "ZZ1000": 2, "CSI_ALL": 3}
    df["_sort"] = df["benchmark_index"].map(idx_order).fillna(9)
    df = df.sort_values(["_sort", "fund_code"]).drop(columns=["_sort"])

    benchmark_order = ["HS300", "ZZ500", "ZZ1000", "CSI_ALL"]

    try:
        writer = pd.ExcelWriter(output_path, engine="xlsxwriter")
    except PermissionError:
        base, ext = os.path.splitext(output_path)
        fallback = f"{base}_{time.strftime('%Y%m%d_%H%M%S')}{ext}"
        print(f"[WARN] {os.path.basename(output_path)} 被占用，改为 {os.path.basename(fallback)}")
        writer = pd.ExcelWriter(fallback, engine="xlsxwriter")
        output_path = fallback

    with writer:
        workbook = writer.book

        # ── 格式 ──
        header_fmt = workbook.add_format({
            "bold": True, "bg_color": "#1a2e3d", "font_color": "#d0d6dc",
            "border": 1, "text_wrap": True, "align": "center", "valign": "vcenter",
            "font_size": 10,
        })
        cell_fmt = workbook.add_format({
            "border": 1, "align": "center", "valign": "vcenter",
            "font_size": 10, "font_name": "Microsoft YaHei",
        })
        cell_left_fmt = workbook.add_format({
            "border": 1, "align": "left", "valign": "vcenter",
            "font_size": 10, "font_name": "Microsoft YaHei", "text_wrap": True,
        })
        pct_fmt = workbook.add_format({
            "border": 1, "align": "center", "valign": "vcenter",
            "font_size": 10, "num_format": "0.00%",
        })
        green_pct = workbook.add_format({
            "border": 1, "align": "center", "valign": "vcenter",
            "font_size": 10, "font_color": "#2ecc71", "num_format": "0.00%",
        })
        red_pct = workbook.add_format({
            "border": 1, "align": "center", "valign": "vcenter",
            "font_size": 10, "font_color": "#f75454", "num_format": "0.00%",
        })
        num_fmt = workbook.add_format({
            "border": 1, "align": "center", "valign": "vcenter",
            "font_size": 10, "num_format": "0.00",
        })

        summary_cols = {"收益能力", "风险控制", "风险调整收益", "超额持续性", "综合画像"}

        for benchmark in benchmark_order:
            group = df[df["benchmark_index"] == benchmark]
            if group.empty:
                continue

            name = INDEX_NAMES.get(benchmark, benchmark)
            sheet_name = f"{name}增强"[:31]

            display = group[col_keys].rename(columns=dict(zip(col_keys, col_names)))
            display.to_excel(writer, sheet_name=sheet_name, index=False, startrow=0)
            ws = writer.sheets[sheet_name]
            n_rows = len(display)

            # 写表头
            for ci, cn in enumerate(col_names):
                ws.write(0, ci, cn, header_fmt)

            # 写数据
            for ri in range(1, n_rows + 1):
                for ci, cn in enumerate(col_names):
                    val = display.iloc[ri - 1, ci]

                    # 摘要列 → 左对齐文本
                    if cn in summary_cols:
                        ws.write(ri, ci, str(val) if pd.notna(val) else "", cell_left_fmt)

                    # 百分比列
                    elif cn in PCT_COLS:
                        if isinstance(val, (int, float)) and not pd.isna(val):
                            if val > 0:
                                ws.write(ri, ci, val, green_pct)
                            elif val < 0:
                                ws.write(ri, ci, val, red_pct)
                            else:
                                ws.write(ri, ci, val, pct_fmt)
                        else:
                            ws.write(ri, ci, "", cell_fmt)

                    # 数值列
                    elif cn in NUM_COLS:
                        if isinstance(val, (int, float)) and not pd.isna(val):
                            ws.write(ri, ci, val, num_fmt)
                        else:
                            ws.write(ri, ci, "", cell_fmt)

                    # 其他
                    else:
                        ws.write(ri, ci, str(val) if pd.notna(val) else "", cell_fmt)

            # 列宽
            width_map = {v: w for _, v, w in available}
            for ci, cn in enumerate(col_names):
                ws.set_column(ci, ci, width_map.get(cn, 14))

            # 冻结首行
            ws.freeze_panes(1, 0)

        # ── 汇总概览 ──
        summary_rows = []
        for benchmark in benchmark_order:
            g = df[df["benchmark_index"] == benchmark]
            if g.empty:
                continue
            pc = g["profile"].value_counts().to_dict()
            summary_rows.append({
                "指数": INDEX_NAMES.get(benchmark, benchmark),
                "基金数量": len(g),
                "稳健增强型": pc.get("稳健增强型", 0),
                "风险收益优化型": pc.get("风险收益优化型", 0),
                "高弹性增强型": pc.get("高弹性增强型", 0),
                "普通增强型": pc.get("普通增强型", 0),
                "指数复制型": pc.get("指数复制型", 0),
                "观察样本": pc.get("观察样本", 0),
                "平均Sharpe": round(g["sharpe_ratio"].dropna().mean(), 2) if "sharpe_ratio" in g.columns else None,
                "平均Calmar": round(g["calmar_ratio"].dropna().mean(), 2) if "calmar_ratio" in g.columns else None,
            })

        sdf = pd.DataFrame(summary_rows)
        sdf.to_excel(writer, sheet_name="汇总概览", index=False, startrow=0)
        ws = writer.sheets["汇总概览"]
        for ci, cn in enumerate(sdf.columns):
            ws.write(0, ci, cn, header_fmt)
        for ri in range(1, len(sdf) + 1):
            for ci in range(len(sdf.columns)):
                val = sdf.iloc[ri - 1, ci]
                ws.write(ri, ci, val if pd.notna(val) else "", cell_fmt)
        for ci in range(len(sdf.columns)):
            ws.set_column(ci, ci, 16)
        ws.freeze_panes(1, 0)

    print(f"[OK] Research analysis exported: {output_path}")
