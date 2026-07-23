import os

import pandas as pd

from config import (
    EXCESS_RETURN_PATH,
    INDEX_NAMES,
)

from analysis.ranking import compute_rankings
from analysis.research_profile import determine_profile
from analysis.research_tags import determine_tags

OUTPUT_HTML = "output/research.html"

# ── 列定义: (列键, 表头, 类型, 小数位数) ──
# type: "pct"=百分比, "num"=数值, "text"=文本
COLUMNS = [
    ("fund_code",         "基金代码",   "code", 0),
    ("fund_name",         "基金简称",   "text", 0),
    ("launch_date",       "成立时间",   "text", 0),
    ("scale",             "成立规模",   "text", 0),
    ("annual_return",     "年化收益",   "pct",  2),
    ("annual_volatility", "年化波动率", "pct",  2),
    ("sharpe_ratio",      "Sharpe",    "num",  2),
    ("max_drawdown",      "最大回撤",   "pct",  2),
    ("calmar_ratio",      "Calmar",    "num",  2),
    ("month_1_alpha",     "1月超额",    "pct",  2),
    ("month_6_alpha",     "6月超额",    "pct",  2),
    ("year_1_alpha",      "年化超额",   "pct",  2),
    ("profile",           "基金画像",   "text", 0),
    ("tags",              "研究标签",   "tags", 0),
]

# 各列缺失时的标注文本
EMPTY_REASON = {
    "month_1_alpha":  "新成立",
    "month_6_alpha":  "成立不足6月",
    "year_1_alpha":   "成立不足1年",
}

PROFILE_COLORS = {
    "稳健增强型":    "#2ecc71",
    "风险收益优化型": "#3d7eff",
    "高弹性增强型":  "#f39c12",
    "普通增强型":    "#8899aa",
    "指数复制型":    "#5a6f80",
    "观察样本":      "#4a5d6e",
}


def load_and_analyze():
    """加载数据并运行完整分析管线"""
    excess = pd.read_parquet(EXCESS_RETURN_PATH)
    latest_date = str(excess["date"].max())
    excess = excess[excess["date"] == excess["date"].max()].copy()

    core_cols = [
        "fund_code", "fund_name", "benchmark_index", "benchmark_name",
        "annual_return", "annual_volatility", "sharpe_ratio",
        "max_drawdown", "calmar_ratio",
        "year_1_alpha", "month_6_alpha", "month_1_alpha",
    ]
    df = excess[[c for c in core_cols if c in excess.columns]].copy()

    # launch_date / scale from cache
    cache_path = os.path.join(os.path.dirname(EXCESS_RETURN_PATH), "..", "fund_detail_cache.parquet")
    cache_path = os.path.normpath(cache_path)
    if os.path.exists(cache_path):
        cache = pd.read_parquet(cache_path)
        if "launch_date" in cache.columns:
            lm = {}
            for _, r in cache.iterrows():
                ld = r["launch_date"]
                if pd.notna(ld) and str(ld) not in ("", "nan", "None"):
                    lm[str(r["fund_code"]).zfill(6)] = str(ld)
            df["launch_date"] = df["fund_code"].map(lm)
        if "scale" in cache.columns:
            sm = {}
            for _, r in cache.iterrows():
                sc = r["scale"]
                if pd.notna(sc) and str(sc) not in ("", "nan", "None"):
                    sm[str(r["fund_code"]).zfill(6)] = str(sc)
            df["scale"] = df["fund_code"].map(sm)

    # 过滤
    alpha_cols = ["year_1_alpha", "month_6_alpha", "month_1_alpha"]
    df = df[df[alpha_cols].notna().any(axis=1)].copy()

    print(f"分析样本: {len(df)} 只")

    # 管线
    df = compute_rankings(df)
    df = determine_profile(df)
    df = determine_tags(df)

    return df, latest_date


def _fmt(val, col_type, decimals, col_key=""):
    """格式化单元格值，NaN 时返回缺失原因"""
    if val is None or (isinstance(val, float) and pd.isna(val)):
        reason = EMPTY_REASON.get(col_key, "N/A")
        return reason, "empty"
    if col_type == "pct":
        v = val * 100
        cls = "positive" if v > 0 else ("negative" if v < 0 else "")
        return f"{v:+.{decimals}f}%", cls
    elif col_type == "num":
        return f"{val:.{decimals}f}", ""
    else:
        return str(val), ""


def _build_table_rows(group, col_keys, col_types, col_decimals):
    """构建表格行 HTML"""
    rows = []
    for _, r in group.iterrows():
        cells = []
        for ck, ct, cd in zip(col_keys, col_types, col_decimals):
            val = r.get(ck)
            if ck == "fund_code":
                cells.append(f'<td class="code">{val}</td>')
            elif ck == "fund_name":
                cells.append(f'<td class="name" title="{val}">{val}</td>')
            elif ck == "launch_date":
                cells.append(f'<td class="launch-date">{str(val) if pd.notna(val) else ""}</td>')
            elif ck == "scale":
                cells.append(f'<td class="scale">{str(val) if pd.notna(val) else ""}</td>')
            elif ck == "profile":
                color = PROFILE_COLORS.get(str(val), "#8899aa")
                cells.append(f'<td style="color:{color};font-weight:600;">{val}</td>')
            elif ck == "tags":
                cells.append(f'<td class="tags">{str(val) if pd.notna(val) else ""}</td>')
            elif ct in ("pct", "num"):
                text, cls = _fmt(val, ct, cd, ck)
                if cls == "empty":
                    cells.append(f'<td class="empty-reason">{text}</td>')
                elif cls:
                    cells.append(f'<td class="{cls}">{text}</td>')
                else:
                    cells.append(f'<td>{text}</td>')
            else:
                cells.append(f'<td>{str(val) if pd.notna(val) else ""}</td>')
        rows.append("<tr>" + "".join(cells) + "</tr>")
    return "\n".join(rows)


def _build_table_html(group, prefix):
    """为单个 benchmark 组构建完整表格 HTML"""
    col_keys = [c[0] for c in COLUMNS if c[0] in group.columns]
    col_names = [c[1] for c in COLUMNS if c[0] in group.columns]
    col_types = [c[2] for c in COLUMNS if c[0] in group.columns]
    col_decimals = [c[3] for c in COLUMNS if c[0] in group.columns]

    # 表头
    headers = []
    for i, (cn, ct) in enumerate(zip(col_names, col_types)):
        sortable = ' class="sortable"' if ct in ("pct", "num") else ""
        btns = ""
        if ct in ("pct", "num"):
            btns = f'''<span class="sort-btns">
              <span class="sort-btn asc" data-col="{i}" data-dir="asc">&#9650;</span>
              <span class="sort-btn desc" data-col="{i}" data-dir="desc">&#9660;</span>
            </span>'''
        headers.append(f'<th{sortable}>{cn}{btns}</th>')

    rows_html = _build_table_rows(group, col_keys, col_types, col_decimals)

    return f"""
      <table class="fund-table">
        <thead><tr>{"".join(headers)}</tr></thead>
        <tbody>{rows_html}</tbody>
      </table>"""


def generate_html(df, date_str="latest"):
    os.makedirs(os.path.dirname(OUTPUT_HTML), exist_ok=True)
    benchmarks = ["HS300", "ZZ500", "ZZ1000", "CSI_ALL"]

    # 构建各组的表格
    tables = {}
    counts = {}
    for bm in benchmarks:
        g = df[df["benchmark_index"] == bm]
        if g.empty:
            continue
        # 排序: 按 sharpe 降序
        if "sharpe_ratio" in g.columns:
            g = g.sort_values("sharpe_ratio", ascending=False)
        tables[bm] = _build_table_html(g, bm)
        counts[bm] = len(g)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>指数增强基金 五指标研究</title>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        font-family: "Microsoft YaHei", "PingFang SC", "Helvetica Neue", Arial, sans-serif;
        background: #0f1923; color: #d0d6dc; padding: 24px 36px; min-height: 100vh;
    }}
    .header {{ text-align: center; margin-bottom: 20px; padding-bottom: 16px;
        border-bottom: 2px solid #1a2d3d; }}
    .header h1 {{ font-size: 24px; font-weight: 600; color: #e8ecf1; letter-spacing: 1px; }}
    .header .meta {{ font-size: 12px; color: #6a8090; margin-top: 6px; }}

    /* ── Tabs ── */
    .tabs {{ display: flex; gap: 4px; margin-bottom: 16px; flex-wrap: wrap; }}
    .tab-btn {{
        padding: 8px 20px; border: 1px solid #1e3040; border-radius: 4px 4px 0 0;
        background: #152028; color: #6a8090; cursor: pointer; font-size: 13px;
        transition: all 0.2s; font-family: inherit;
    }}
    .tab-btn:hover {{ color: #b0c0d0; border-color: #253d50; }}
    .tab-btn.active {{ background: #1a2e3d; color: #e8ecf1; border-color: #3d7eff; border-bottom-color: #1a2e3d; }}

    /* ── Table ── */
    .table-wrapper {{ background: #152028; border: 1px solid #1e3040; border-radius: 0 6px 6px 6px; overflow-x: auto; display: none; }}
    .table-wrapper.active {{ display: block; }}

    table {{ border-collapse: collapse; width: 100%; table-layout: fixed; min-width: 1200px; }}
    thead th {{
        background: #1a2e3d; color: #8899aa; font-size: 12px; font-weight: 500;
        padding: 12px 6px; text-align: center; border-bottom: 2px solid #253d50;
        position: sticky; top: 0; z-index: 10; white-space: nowrap;
    }}
    thead th.sortable {{ cursor: pointer; }}
    thead th.sortable:hover {{ color: #b0c0d0; }}

    tbody td {{
        padding: 8px 6px; font-size: 12px; text-align: center;
        border-bottom: 1px solid #1a2a35; color: #c8d0d8;
        font-variant-numeric: tabular-nums; white-space: nowrap;
    }}
    tbody tr {{ transition: background 0.15s; }}
    tbody tr:nth-child(even) {{ background: #182530; }}
    tbody tr:hover {{ background: #1c3040; }}

    td.code {{ color: #6a8090; font-family: "SF Mono","Consolas","Menlo",monospace; font-size: 13px; }}
    td.name {{ color: #d8dfe6; font-weight: 450; max-width: 160px; overflow: hidden; text-overflow: ellipsis; }}
    td.tags {{ font-size: 11px; text-align: left; max-width: 200px; color: #8899aa; }}

    td.positive {{ color: #f75454; font-weight: 500; }}
    td.negative {{ color: #2ecc71; font-weight: 500; }}
    td.empty-reason {{ color: #4a5d6e; font-size: 11px; font-weight: 400; }}

    /* ── Sort buttons ── */
    .sort-btns {{ display: inline-flex; flex-direction: column; vertical-align: middle; margin-left: 3px; line-height: 1; cursor: pointer; user-select: none; }}
    .sort-btn {{ font-size: 9px; color: #3d5060; line-height: 1; padding: 0; transition: color 0.15s; }}
    .sort-btn:hover {{ color: #8899aa; }}
    .sort-btn.active {{ color: #3d7eff; }}

    /* ── Footnote ── */
    .footnote {{ margin-top: 16px; padding: 10px 16px; background: #152028; border: 1px solid #1e3040; border-radius: 4px; color: #5a6f80; font-size: 11px; }}
    .footnote span {{ margin-right: 24px; }}
    .legend-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%; margin-right: 4px; vertical-align: middle; }}
</style>
</head>
<body>

<div class="header">
    <h1>指数增强基金 五指标研究</h1>
    <span class="meta">数据日期: {date_str} &nbsp;|&nbsp; 共 {len(df)} 只基金 &nbsp;|&nbsp;
      {", ".join(f"{INDEX_NAMES.get(bm, bm)} {counts.get(bm, 0)}只" for bm in benchmarks if bm in tables)}</span>
</div>

<div class="tabs">
{"".join(f'<div class="tab-btn{" active" if i==0 else ""}" data-tab="{bm}">{INDEX_NAMES.get(bm,bm)} ({counts.get(bm,0)})</div>' for i, bm in enumerate(benchmarks) if bm in tables)}
</div>

{"".join(f'<div class="table-wrapper{" active" if i==0 else ""}" id="table-{bm}">\n{tables[bm]}\n</div>' for i, bm in enumerate(benchmarks) if bm in tables)}

<div class="footnote">
    <p>
      <span><span class="legend-dot" style="background:#f75454;"></span> 正收益/超额</span>
      <span><span class="legend-dot" style="background:#2ecc71;"></span> 负收益/超额</span>
      <span style="margin-left:16px;">Profile:
        <span style="color:#2ecc71;">稳健增强</span> &mdash; Alpha正向，风险可控；
        <span style="color:#3d7eff;">风险收益优化</span> &mdash; Sharpe/Calmar居前；
        <span style="color:#f39c12;">高弹性增强</span> &mdash; 收益高但波动/回撤大；
        <span style="color:#8899aa;">普通增强</span> &mdash; 各项居中；
        <span style="color:#5a6f80;">指数复制</span> &mdash; 各周期Alpha均未跑赢基准，增强特征不明显，更像被动跟踪指数
      </span>
    </p>
    <p style="margin-top:4px;">
      灰色标注 "成立不足1年/6月" 或 "新成立" 表示该周期数据因基金成立时间较短而暂缺。
      点击列表头箭头可排序（升序/降序）。数据基于历史净值，不构成投资建议。
    </p>
</div>

<script>
(function() {{
    // ── Tab 切换 ──
    var tabBtns = document.querySelectorAll('.tab-btn');
    tabBtns.forEach(function(btn) {{
        btn.addEventListener('click', function() {{
            var tab = this.getAttribute('data-tab');
            tabBtns.forEach(function(b) {{ b.classList.remove('active'); }});
            this.classList.add('active');
            document.querySelectorAll('.table-wrapper').forEach(function(t) {{ t.classList.remove('active'); }});
            document.getElementById('table-' + tab).classList.add('active');
        }});
    }});

    // ── 排序 ──
    document.querySelectorAll('.fund-table').forEach(function(table) {{
        var tbody = table.querySelector('tbody');
        var headers = table.querySelectorAll('th');

        headers.forEach(function(th, colIdx) {{
            var ascBtn = th.querySelector('.sort-btn.asc');
            var descBtn = th.querySelector('.sort-btn.desc');
            if (!ascBtn || !descBtn) return;

            ascBtn.addEventListener('click', function(e) {{
                e.stopPropagation();
                resetAllArrows(table);
                ascBtn.classList.add('active');
                sortTable(table, colIdx, 'asc');
            }});

            descBtn.addEventListener('click', function(e) {{
                e.stopPropagation();
                resetAllArrows(table);
                descBtn.classList.add('active');
                sortTable(table, colIdx, 'desc');
            }});

            th.addEventListener('click', function(e) {{
                resetAllArrows(table);
                sortDefault(table);
            }});
        }});
    }});

    function resetAllArrows(table) {{
        table.querySelectorAll('.sort-btn').forEach(function(b) {{ b.classList.remove('active'); }});
    }}

    function parseVal(td) {{
        var text = td.textContent.trim();
        // 百分比: +12.34% or -5.67%
        var m = text.match(/^([+\\-]?\\d+\\.?\\d*)%$/);
        if (m) return parseFloat(m[1]);
        // 纯数字
        var n = parseFloat(text);
        return isNaN(n) ? (text === '' ? -Infinity : -Infinity) : n;
    }}

    function sortTable(table, colIdx, dir) {{
        var tbody = table.querySelector('tbody');
        var rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort(function(a, b) {{
            var aVal = parseVal(a.querySelectorAll('td')[colIdx]);
            var bVal = parseVal(b.querySelectorAll('td')[colIdx]);
            if (aVal === -Infinity && bVal === -Infinity) return 0;
            if (aVal === -Infinity) return 1;
            if (bVal === -Infinity) return -1;
            return dir === 'asc' ? aVal - bVal : bVal - aVal;
        }});
        rows.forEach(function(r) {{ tbody.appendChild(r); }});
    }}

    function sortDefault(table) {{
        var tbody = table.querySelector('tbody');
        var rows = Array.from(tbody.querySelectorAll('tr'));
        rows.sort(function(a, b) {{
            var aVal = a.querySelector('td.code').textContent.trim();
            var bVal = b.querySelector('td.code').textContent.trim();
            return aVal.localeCompare(bVal);
        }});
        rows.forEach(function(r) {{ tbody.appendChild(r); }});
    }}
}})();
</script>
</body>
</html>
"""

    with open(OUTPUT_HTML, "w", encoding="utf-8") as f:
        f.write(html)

    print(f"[OK] Research HTML exported: {OUTPUT_HTML}")
    for bm in benchmarks:
        if bm in counts:
            print(f"  {INDEX_NAMES.get(bm, bm)}: {counts[bm]} 只")


def main():
    print("\n" + "█" * 60)
    print("█  基金研究解读 HTML ")
    print("█  五核心指标 + 排序 + Profile + Tags")
    print("█" * 60)

    df, date_str = load_and_analyze()
    if df.empty:
        print("[ERROR] No data")
        return

    generate_html(df, date_str)

    print("\nDone!")


if __name__ == "__main__":
    main()
