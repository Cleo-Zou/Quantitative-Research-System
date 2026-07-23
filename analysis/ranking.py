import pandas as pd

from config import (
    MIN_SAMPLE_PERCENTILE,
    TOP_EXCELLENT,
    TOP_GOOD,
    BOTTOM_WEAK,
    MDD_WORST_PCT,
)


def _rank_and_pct(group: pd.DataFrame, col: str, ascending: bool = True) -> pd.DataFrame:
    rank_col = f"{col}_rank"
    pct_col = f"{col}_pct"

    group = group.copy()
    valid = group[col].notna()
    n = valid.sum()

    if n == 0:
        group[rank_col] = pd.NA
        group[pct_col] = pd.NA
        return group

    ranks = group.loc[valid, col].rank(ascending=ascending, method="min")
    group.loc[valid, rank_col] = ranks.astype(int)
    group.loc[valid, pct_col] = (ranks / n * 100).round(1)
    return group


def compute_rankings(df: pd.DataFrame) -> pd.DataFrame:
    result_parts = []
    # 指标列表: (列名, 方向说明)
    # ascending=True → 值大排前面 (rank=1 最好)
    metric_cols = [
        # ── 五核心 ──
        "annual_return",
        "annual_volatility",   # ascending=True → 低波动排前面（rank=1 = 波动最小）
        "sharpe_ratio",
        "max_drawdown",        # ascending=True → 负得少排前面（rank=1 = 回撤最小）
        "calmar_ratio",
        # ── Alpha ──
        "year_1_alpha",
        "month_6_alpha",
        "month_1_alpha",
        # ── 超额风险指标 ──
        "excess_annual_return",   # ascending=True → 超额年化收益越高越好
        "tracking_error",          # ascending=True → 跟踪误差越低越好
        "information_ratio",       # ascending=True → IR 越高越好
        "excess_max_drawdown",     # ascending=True → 超额回撤越小越好
        "excess_calmar",           # ascending=True → 超额卡玛越高越好
    ]

    for benchmark, group in df.groupby("benchmark_index"):
        group = group.copy()
        n = len(group)

        group["is_small_sample"] = n < MIN_SAMPLE_PERCENTILE

        for col in metric_cols:
            if col in group.columns:
                group = _rank_and_pct(group, col, ascending=True)

        result_parts.append(group)

    result = pd.concat(result_parts, ignore_index=True)

    # ── 布尔标记 ──
    result["is_alpha_excellent"] = False
    result["is_alpha_good"] = False
    result["is_alpha_weak"] = False
    result["is_return_good"] = False
    result["is_sharpe_good"] = False
    result["is_calmar_good"] = False
    result["is_vol_low"] = False
    result["is_vol_high"] = False
    result["is_drawdown_worst"] = False
    result["is_drawdown_low"] = False
    result["is_excess_return_good"] = False
    result["is_tracking_error_low"] = False
    result["is_ir_good"] = False
    result["is_excess_mdd_low"] = False
    result["is_excess_calmar_good"] = False

    for idx, row in result.iterrows():
        a_pct = row.get("year_1_alpha_pct")
        r_pct = row.get("annual_return_pct")
        s_pct = row.get("sharpe_ratio_pct")
        c_pct = row.get("calmar_ratio_pct")
        v_pct = row.get("annual_volatility_pct")
        m_pct = row.get("max_drawdown_pct")

        # ── Alpha ──
        if pd.notna(a_pct):
            a_val = row.get("year_1_alpha")
            if a_pct <= TOP_EXCELLENT * 100 and pd.notna(a_val) and a_val > 0:
                result.at[idx, "is_alpha_excellent"] = True
            if a_pct <= TOP_GOOD * 100 and pd.notna(a_val) and a_val > 0:
                result.at[idx, "is_alpha_good"] = True
            if a_pct >= (1 - BOTTOM_WEAK) * 100:
                result.at[idx, "is_alpha_weak"] = True

        # ── 年化收益（必须 > 0 才有意义）──
        if pd.notna(r_pct) and r_pct <= TOP_GOOD * 100:
            r_val = row.get("annual_return")
            if pd.notna(r_val) and r_val > 0:
                result.at[idx, "is_return_good"] = True

        # ── Sharpe（必须 > 0 才有意义）──
        if pd.notna(s_pct) and s_pct <= TOP_GOOD * 100:
            s_val = row.get("sharpe_ratio")
            if pd.notna(s_val) and s_val > 0:
                result.at[idx, "is_sharpe_good"] = True

        # ── Calmar（必须 > 0 才有意义）──
        if pd.notna(c_pct) and c_pct <= TOP_GOOD * 100:
            c_val = row.get("calmar_ratio")
            if pd.notna(c_val) and c_val > 0:
                result.at[idx, "is_calmar_good"] = True

        # ── 波动率（ascending=True → 低波动 pct 小 → pct 小 = 好）──
        if pd.notna(v_pct):
            if v_pct <= TOP_GOOD * 100:
                result.at[idx, "is_vol_low"] = True
            if v_pct >= (1 - BOTTOM_WEAK) * 100:
                result.at[idx, "is_vol_high"] = True

        # ── 最大回撤（ascending=True → 回撤小 pct 小 → pct 小 = 好）──
        if pd.notna(m_pct):
            if m_pct <= TOP_GOOD * 100:
                result.at[idx, "is_drawdown_low"] = True
            if m_pct <= MDD_WORST_PCT * 100:
                result.at[idx, "is_drawdown_worst"] = True

        # ── 超额年化收益 ──
        ea_pct = row.get("excess_annual_return_pct")
        if pd.notna(ea_pct) and ea_pct <= TOP_GOOD * 100:
            ea_val = row.get("excess_annual_return")
            if pd.notna(ea_val) and ea_val > 0:
                result.at[idx, "is_excess_return_good"] = True

        # ── 跟踪误差（ascending → 低 TE pct 小 = 好）──
        te_pct = row.get("tracking_error_pct")
        if pd.notna(te_pct) and te_pct <= TOP_GOOD * 100:
            result.at[idx, "is_tracking_error_low"] = True

        # ── 信息比率 ──
        ir_pct = row.get("information_ratio_pct")
        if pd.notna(ir_pct) and ir_pct <= TOP_GOOD * 100:
            ir_val = row.get("information_ratio")
            if pd.notna(ir_val) and ir_val > 0:
                result.at[idx, "is_ir_good"] = True

        # ── 超额最大回撤 ──
        em_pct = row.get("excess_max_drawdown_pct")
        if pd.notna(em_pct) and em_pct <= TOP_GOOD * 100:
            result.at[idx, "is_excess_mdd_low"] = True

        # ── 超额卡玛 ──
        ec_pct = row.get("excess_calmar_pct")
        if pd.notna(ec_pct) and ec_pct <= TOP_GOOD * 100:
            ec_val = row.get("excess_calmar")
            if pd.notna(ec_val) and ec_val > 0:
                result.at[idx, "is_excess_calmar_good"] = True

    return result
