import os

import pandas as pd

from config import (
    EXCESS_RETURN_PATH,
    INDEX_NAMES,
)

from analysis.ranking import compute_rankings
from analysis.research_profile import determine_profile
from analysis.research_tags import determine_tags
from analysis.research_summary import generate_summaries

OUTPUT_HTML = "output/research.html"

# ═══════════════════════════════════════════════════════════════
#  子标签页列定义
# ═══════════════════════════════════════════════════════════════
# type: "pct"=百分比, "num"=数值, "text"=文本, "code"=代码, "tags"=标签

CORE_COLUMNS = [
    ("fund_code",         "基金代码",   "code", 0),
    ("fund_name",         "基金简称",   "text", 0),
    ("launch_date",       "成立时间",   "text", 0),
    ("scale",             "成立规模",   "text", 0),
    ("annual_return",     "年化收益",   "pct",  2),
    ("annual_volatility", "年化波动率", "pct",  2),
    ("sharpe_ratio",      "Sharpe",    "num",  2),
    ("max_drawdown",      "最大回撤",   "pct",  2),
    ("calmar_ratio",      "Calmar",    "num",  2),
]

EXCESS_COLUMNS = [
    ("fund_code",             "基金代码",     "code", 0),
    ("fund_name",             "基金简称",     "text", 0),
    ("month_1_alpha",         "1月Alpha",    "pct",  2),
    ("month_6_alpha",         "6月Alpha",    "pct",  2),
    ("year_1_alpha",          "年化Alpha",   "pct",  2),
    ("excess_annual_return",  "超额年化收益", "pct",  2),
    ("tracking_error",        "跟踪误差",     "pct",  2),
    ("information_ratio",     "信息比率IR",   "num",  2),
    ("excess_max_drawdown",   "超额最大回撤", "pct",  2),
    ("excess_calmar",         "超额Calmar",  "num",  2),
]

EVAL_COLUMNS = [
    ("fund_code",           "基金代码",   "code", 0),
    ("fund_name",           "基金简称",   "text", 0),
    ("profile",             "基金画像",   "text", 0),
    ("tags",                "研究标签",   "tags", 0),
    ("return_summary",      "收益能力",   "text", 0),
    ("risk_summary",        "风险控制",   "text", 0),
    ("risk_adj_summary",    "风险调整",   "text", 0),
    ("consistency_summary", "超额持续性", "text", 0),
    ("summary_comment",     "综合评价",   "text", 0),
]

SUB_TABS = [
    ("core",  "核心指标", CORE_COLUMNS),
    ("excess","超额分析", EXCESS_COLUMNS),
    ("eval",  "综合评价", EVAL_COLUMNS),
]

# 各列缺失时的标注文本
EMPTY_REASON = {
    "month_1_alpha":        "成立不足1月",
    "month_6_alpha":        "成立不足6月",
    "year_1_alpha":         "成立不足1年",
    "excess_annual_return": "数据不足",
    "tracking_error":       "数据不足",
    "information_ratio":    "数据不足",
    "excess_max_drawdown":  "数据不足",
    "excess_calmar":        "数据不足",
}

PROFILE_COLORS = {
    "稳健增强型":    "#2ecc71",
    "风险收益优化型": "#3d7eff",
    "高弹性增强型":  "#f39c12",
    "普通增强型":    "#8899aa",
    "指数复制型":    "#5a6f80",
    "观察样本":      "#4a5d6e",
}

SUB_TAB_LABELS = {
    "core":   "核心指标",
    "excess": "超额分析",
    "eval":   "综合评价",
}

SUB_TAB_DESC = {
    "core":   "五核心风险收益指标（同类排名百分位），衡量基金绝对表现。",
    "excess": "超额收益与主动管理风险指标（基于日度超额序列），衡量主动管理能力。<br>"
             "IR &gt; 1.0 = 优秀，0.5 = 及格；跟踪误差越低 = 超额越稳定。",
    "eval":   "规则引擎自动生成的研究画像、标签与五段研究摘要。",
}


# ═══════════════════════════════════════════════════════════════
#  数据加载 & 分析管线
# ═══════════════════════════════════════════════════════════════

def load_and_analyze():
    """加载数据并运行完整分析管线（含研究摘要）。"""
    excess = pd.read_parquet(EXCESS_RETURN_PATH)
    latest_date = str(excess["date"].max())
    excess = excess[excess["date"] == excess["date"].max()].copy()

    # 全量加载（不再限制列，让各子表自行筛选可用列）
    df = excess.copy()

    # launch_date / scale from whitelist Excel
    xls_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "data", "fund_whitelist.xlsx")
    xls_path = os.path.normpath(xls_path)
    if os.path.exists(xls_path):
        launch_map = {}
        scale_map = {}
        for sheet in pd.ExcelFile(xls_path).sheet_names:
            sdf = pd.read_excel(xls_path, sheet_name=sheet, dtype=str)
            if sdf.shape[1] >= 3:
                for _, r in sdf.iterrows():
                    code = str(r.iloc[0]).strip().replace(".OF", "").zfill(6)
                    ld = str(r.iloc[2]) if pd.notna(r.iloc[2]) and str(r.iloc[2]) not in ("nan", "获取失败") else None
                    sc = str(r.iloc[3]) if sdf.shape[1] >= 4 and pd.notna(r.iloc[3]) and str(r.iloc[3]) not in ("nan", "获取失败") else None
                    if ld:
                        launch_map[code] = ld
                    if sc:
                        scale_map[code] = sc
        df["launch_date"] = df["fund_code"].map(launch_map)
        df["scale"] = df["fund_code"].map(scale_map)

    # 过滤：至少有一个周期的 Alpha 数据
    alpha_cols = ["year_1_alpha", "month_6_alpha", "month_1_alpha"]
    df = df[df[alpha_cols].notna().any(axis=1)].copy()

    print(f"分析样本: {len(df)} 只")

    # 完整管线
    df = compute_rankings(df)
    df = determine_profile(df)
    df = determine_tags(df)
    df = generate_summaries(df)

    return df, latest_date


# ═══════════════════════════════════════════════════════════════
#  格式化 & 渲染
# ═══════════════════════════════════════════════════════════════

def _fmt(val, col_type, decimals, col_key=""):
    """格式化单元格值，NaN 时返回缺失原因。"""
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


def _build_table_rows(group, col_defs):
    """根据列定义构建表格行 HTML。col_defs 已过滤为实际存在的列。"""
    rows = []
    for _, r in group.iterrows():
        cells = []
        for ck, _cn, ct, cd in col_defs:
            val = r.get(ck)
            if ck == "fund_code":
                cells.append(f'<td class="code">{val}</td>')
            elif ck == "fund_name":
                cells.append(f'<td class="name" title="{val}">{val}</td>')
            elif ck == "launch_date":
                cells.append(f'<td class="muted">{str(val)[:10] if pd.notna(val) else ""}</td>')
            elif ck == "scale":
                cells.append(f'<td class="muted">{str(val) if pd.notna(val) else ""}</td>')
            elif ck == "profile":
                color = PROFILE_COLORS.get(str(val), "#8899aa")
                cells.append(f'<td style="color:{color};font-weight:600;">{val}</td>')
            elif ck == "tags":
                cells.append(f'<td class="tags">{str(val) if pd.notna(val) else ""}</td>')
            elif ck.startswith("return_summary") or ck.startswith("risk_") or ck.startswith("consistency_") or ck == "summary_comment":
                text = str(val) if pd.notna(val) else ""
                cells.append(f'<td class="summary-cell" title="{_escape_attr(text)}">{text}</td>')
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


def _escape_attr(text: str) -> str:
    """转义 HTML 属性中的引号。"""
    return text.replace("&", "&amp;").replace('"', "&quot;").replace("<", "&lt;")


def _build_table_html(group, col_defs):
    """为单个子标签页构建完整表格 HTML。col_defs 已过滤。"""
    if not col_defs:
        return '<div class="empty-tab">暂无数据</div>'

    col_keys = [c[0] for c in col_defs]
    col_names = [c[1] for c in col_defs]
    col_types = [c[2] for c in col_defs]
    col_decimals = [c[3] for c in col_defs]

    # 表头
    headers = []
    for i, (cn, ct) in enumerate(zip(col_names, col_types)):
        sortable = ' class="sortable"' if ct in ("pct", "num") else ""
        btns = ""
        if ct in ("pct", "num"):
            btns = (
                '<span class="sort-btns">'
                f'<span class="sort-btn asc" data-col="{i}" data-dir="asc">&#9650;</span>'
                f'<span class="sort-btn desc" data-col="{i}" data-dir="desc">&#9660;</span>'
                '</span>'
            )
        headers.append(f'<th{sortable}>{cn}{btns}</th>')

    rows_html = _build_table_rows(group, col_defs)

    # 根据列数动态调整 table layout
    layout = "auto" if any(c[2] == "text" and c[0].endswith("summary") for c in col_defs) else "fixed"
    min_w = len(col_keys) * 110 if layout == "fixed" else len(col_keys) * 140

    return f"""
      <table class="fund-table" style="table-layout:{layout};min-width:{min_w}px;">
        <thead><tr>{"".join(headers)}</tr></thead>
        <tbody>{rows_html}</tbody>
      </table>"""


# ═══════════════════════════════════════════════════════════════
#  HTML 生成
# ═══════════════════════════════════════════════════════════════

def generate_html(df, date_str="latest"):
    os.makedirs(os.path.dirname(OUTPUT_HTML), exist_ok=True)
    benchmarks = ["HS300", "ZZ500", "ZZ1000", "CSI_ALL"]

    # ── 预构建所有 benchmark × sub-tab 的表格 ──
    all_tables: dict[str, dict[str, str]] = {}  # {bm: {subtab_key: html}}
    counts: dict[str, int] = {}
    bm_has_data: list[str] = []

    for bm in benchmarks:
        g = df[df["benchmark_index"] == bm]
        if g.empty:
            continue
        # 排序: 按 information_ratio 降序（存在时），否则按 sharpe
        sort_col = "information_ratio" if "information_ratio" in g.columns else "sharpe_ratio"
        if sort_col in g.columns:
            g = g.sort_values(sort_col, ascending=False)
        bm_has_data.append(bm)
        counts[bm] = len(g)

        sub_tables = {}
        for subtab_key, _label, col_defs in SUB_TABS:
            # 仅保留实际存在于 df 中的列
            available = [(k, v, t, d) for k, v, t, d in col_defs if k in g.columns]
            sub_tables[subtab_key] = _build_table_html(g, available)
        all_tables[bm] = sub_tables

    if not bm_has_data:
        print("[WARN] 无任何 benchmark 数据")
        return

    # ── 构建 HTML ──
    # Benchmark tab 按钮
    tab_btns_html = "".join(
        f'<div class="tab-btn{" active" if i == 0 else ""}" data-tab="{bm}">'
        f'{INDEX_NAMES.get(bm, bm)}<span class="tab-count">{counts.get(bm, 0)}</span></div>'
        for i, bm in enumerate(bm_has_data)
    )

    # 每个 benchmark 的内容区
    wrappers_parts = []
    for bi, bm in enumerate(bm_has_data):
        sub_tabs = all_tables[bm]

        # 子标签页按钮
        sub_btns_parts = []
        for j, (stk, _label, _cols) in enumerate(SUB_TABS):
            active_cls = " active" if j == 0 else ""
            sub_btns_parts.append(
                f'<div class="sub-tab-btn{active_cls}" data-subtab="{bm}-{stk}">'
                f'{SUB_TAB_LABELS.get(stk, stk)}</div>'
            )
        sub_btns = "".join(sub_btns_parts)

        # 子标签页内容
        sub_wrappers_parts = []
        for j, (stk, _label, _cols) in enumerate(SUB_TABS):
            active_cls = " active" if j == 0 else ""
            table_content = sub_tabs.get(stk, '<div class="empty-tab">暂无数据</div>')
            sub_wrappers_parts.append(
                f'<div class="sub-table-wrapper{active_cls}" id="subtable-{bm}-{stk}">'
                f'<div class="sub-tab-desc">{SUB_TAB_DESC.get(stk, "")}</div>'
                f'{table_content}'
                f'</div>'
            )
        sub_wrappers = "".join(sub_wrappers_parts)

        wrappers_parts.append(f"""
        <div class="table-wrapper{" active" if bi == 0 else ""}" id="table-{bm}">
          <div class="sub-tabs">{sub_btns}</div>
          {sub_wrappers}
        </div>""")

    wrappers_html = "".join(wrappers_parts)

    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>指数增强基金 量化研究看板</title>
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

    /* ── Benchmark Tabs ── */
    .tabs {{ display: flex; gap: 4px; margin-bottom: 12px; flex-wrap: wrap; }}
    .tab-btn {{
        padding: 9px 22px; border: 1px solid #1e3040; border-radius: 4px 4px 0 0;
        background: #152028; color: #6a8090; cursor: pointer; font-size: 13px;
        transition: all 0.2s; font-family: inherit; position: relative;
    }}
    .tab-btn:hover {{ color: #b0c0d0; border-color: #253d50; }}
    .tab-btn.active {{ background: #1a2e3d; color: #e8ecf1; border-color: #3d7eff; border-bottom-color: #1a2e3d; }}
    .tab-count {{ font-size: 11px; color: #5a6f80; margin-left: 4px; }}

    /* ── Sub Tabs ── */
    .sub-tabs {{ display: flex; gap: 0; padding: 8px 12px 0 12px;
        background: #1a2e3d; border-radius: 0 0 0 0; }}
    .sub-tab-btn {{
        padding: 6px 18px; border: 1px solid transparent; border-bottom: none;
        border-radius: 3px 3px 0 0; background: transparent; color: #6a8090;
        cursor: pointer; font-size: 12px; transition: all 0.2s; font-family: inherit;
        margin-right: 2px;
    }}
    .sub-tab-btn:hover {{ color: #b0c0d0; background: rgba(61,126,255,0.06); }}
    .sub-tab-btn.active {{
        background: #152028; color: #e8ecf1; border-color: #253d50;
    }}

    /* ── Wrappers ── */
    .table-wrapper {{ display: none; }}
    .table-wrapper.active {{ display: block; }}
    .sub-table-wrapper {{ display: none; }}
    .sub-table-wrapper.active {{ display: block; }}

    .sub-tab-desc {{
        padding: 8px 16px; font-size: 11px; color: #5a6f80;
        background: #152028; border-left: 1px solid #1e3040; border-right: 1px solid #1e3040;
    }}

    /* ── Table ── */
    .fund-table {{
        border-collapse: collapse; width: 100%;
        border: 1px solid #1e3040; border-top: none;
    }}
    thead th {{
        background: #1a2e3d; color: #8899aa; font-size: 12px; font-weight: 500;
        padding: 10px 6px; text-align: center; border-bottom: 2px solid #253d50;
        position: sticky; top: 0; z-index: 10; white-space: nowrap;
    }}
    thead th.sortable {{ cursor: pointer; }}
    thead th.sortable:hover {{ color: #b0c0d0; }}

    tbody td {{
        padding: 7px 6px; font-size: 12px; text-align: center;
        border-bottom: 1px solid #1a2a35; color: #c8d0d8;
        font-variant-numeric: tabular-nums; white-space: nowrap;
    }}
    tbody tr {{ transition: background 0.15s; }}
    tbody tr:nth-child(even) {{ background: #182530; }}
    tbody tr:hover {{ background: #1c3040; }}

    td.code {{ color: #6a8090; font-family: "SF Mono","Consolas","Menlo",monospace; font-size: 13px; }}
    td.name {{ color: #d8dfe6; font-weight: 450; max-width: 160px; overflow: hidden; text-overflow: ellipsis; }}
    td.tags {{ font-size: 11px; text-align: left; max-width: 220px; color: #8899aa; white-space: normal; }}
    td.muted {{ color: #5a6f80; font-size: 11px; }}

    td.positive {{ color: #f75454; font-weight: 500; }}
    td.negative {{ color: #2ecc71; font-weight: 500; }}
    td.empty-reason {{ color: #4a5d6e; font-size: 11px; font-weight: 400; }}

    /* ── Summary 列 ── */
    td.summary-cell {{
        text-align: left; max-width: 260px; overflow: hidden;
        text-overflow: ellipsis; white-space: nowrap;
        font-size: 11px; color: #8899aa; cursor: default;
    }}
    td.summary-cell:hover {{ color: #b0c0d0; }}

    /* ── Sort buttons ── */
    .sort-btns {{ display: inline-flex; flex-direction: column; vertical-align: middle;
        margin-left: 3px; line-height: 1; cursor: pointer; user-select: none; }}
    .sort-btn {{ font-size: 9px; color: #3d5060; line-height: 1; padding: 0; transition: color 0.15s; }}
    .sort-btn:hover {{ color: #8899aa; }}
    .sort-btn.active {{ color: #3d7eff; }}

    /* ── Empty ── */
    .empty-tab {{ padding: 32px; text-align: center; color: #4a5d6e; font-size: 13px;
        background: #152028; border: 1px solid #1e3040; }}

    /* ── Footnote ── */
    .footnote {{ margin-top: 16px; padding: 10px 16px; background: #152028;
        border: 1px solid #1e3040; border-radius: 4px; color: #5a6f80; font-size: 11px; }}
    .footnote span {{ margin-right: 24px; }}
    .legend-dot {{ display: inline-block; width: 10px; height: 10px; border-radius: 50%;
        margin-right: 4px; vertical-align: middle; }}
</style>
</head>
<body>

<div class="header">
    <h1>指数增强基金 量化研究看板</h1>
    <span class="meta">数据日期: {date_str} &nbsp;|&nbsp; 共 {len(df)} 只基金 &nbsp;|&nbsp;
      {", ".join(f"{INDEX_NAMES.get(bm, bm)} {counts.get(bm, 0)}只" for bm in bm_has_data)}</span>
</div>

<div class="tabs">
{tab_btns_html}
</div>

{wrappers_html}

<div class="footnote">
    <p>
      <span><span class="legend-dot" style="background:#f75454;"></span> 正收益/超额</span>
      <span><span class="legend-dot" style="background:#2ecc71;"></span> 负收益/超额</span>
      <span style="margin-left:12px;">Profile:</span>
      <span style="color:#2ecc71;">稳健增强</span> &mdash; Alpha正向，风险可控；
      <span style="color:#3d7eff;">风险收益优化</span> &mdash; Sharpe/Calmar居前；
      <span style="color:#f39c12;">高弹性增强</span> &mdash; 收益高但波动/回撤大；
      <span style="color:#8899aa;">普通增强</span> &mdash; 各项居中；
      <span style="color:#5a6f80;">指数复制</span> &mdash; 增强特征不明显
    </p>
    <p style="margin-top:4px;">
      灰色标注 "成立不足1年/6月" 表示该周期数据暂缺。"数据不足" 表示日度超额序列不足20个交易日。
      点击列表头箭头可排序。IR = 信息比率 = 超额年化收益÷跟踪误差（主动管理能力的黄金标准）。
      数据基于历史净值，不构成投资建议。
    </p>
</div>

<script>
(function() {{
    // ── Benchmark Tab 切换 ──
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

    // ── Sub-Tab 切换 ──
    document.querySelectorAll('.sub-tab-btn').forEach(function(btn) {{
        btn.addEventListener('click', function() {{
            var subtab = this.getAttribute('data-subtab');   // e.g. "HS300-core"
            var wrapper = this.closest('.table-wrapper');

            // 反激活同 wrapper 下的所有 sub-tab
            wrapper.querySelectorAll('.sub-tab-btn').forEach(function(b) {{ b.classList.remove('active'); }});
            this.classList.add('active');

            wrapper.querySelectorAll('.sub-table-wrapper').forEach(function(st) {{ st.classList.remove('active'); }});
            var target = document.getElementById('subtable-' + subtab);
            if (target) target.classList.add('active');
        }});
    }});

    // ── 表格排序 ──
    document.querySelectorAll('.fund-table').forEach(function(table) {{
        var tbody = table.querySelector('tbody');
        if (!tbody) return;
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
        var m = text.match(/^([+\\-]?\\d+\\.?\\d*)%$/);
        if (m) return parseFloat(m[1]);
        var n = parseFloat(text);
        return isNaN(n) ? -Infinity : n;
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

    print(f"\n[OK] Research HTML exported: {OUTPUT_HTML}")
    for bm in bm_has_data:
        print(f"  {INDEX_NAMES.get(bm, bm)}: {counts[bm]} 只 (3 子标签页)")


# ═══════════════════════════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════════════════════════

def main():
    print("\n" + "█" * 60)
    print("█  基金量化研究看板")
    print("█  核心指标 · 超额分析 · 综合评价 — 三子标签页")
    print("█" * 60)

    df, date_str = load_and_analyze()
    if df.empty:
        print("[ERROR] No data")
        return

    generate_html(df, date_str)

    print("\nDone!")


if __name__ == "__main__":
    main()
