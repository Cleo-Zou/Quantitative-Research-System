"""
研究摘要（Research Summary）自动拼装

五段模板（融合导师要求的五核心指标 + Alpha）:
    ① Return      — 收益能力（Annual Return + Annual Alpha）
    ② Risk        — 风险控制（Annual Volatility + Max Drawdown）
    ③ Risk-Adjusted — 风险调整收益（Sharpe + Calmar）
    ④ Consistency — 超额持续性（Alpha 趋势）
    ⑤ Summary     — 综合画像
"""

import pandas as pd
import numpy as np

from config import (
    ALPHA_EXCELLENT_ABS,
    ALPHA_NEUTRAL,
    ALPHA_WEAK_ABS,
    TREND_TOLERANCE,
)


def _pct_of(v: float | None) -> str:
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v * 100:.1f}%"


def _rank_of(row, col: str) -> str:
    pct_col = f"{col}_pct"
    val = row.get(pct_col)
    if pd.isna(val):
        return "N/A"
    return f"前 {val:.0f}%"


def _better_than(row, col: str) -> str:
    pct_col = f"{col}_pct"
    val = row.get(pct_col)
    if pd.isna(val):
        return "N/A"
    return f"{100 - val:.0f}%"


# ═══════════════════════════════════════════
#  ① Return — 收益能力
# ═══════════════════════════════════════════

def _return_summary(row) -> str:
    ar = row.get("annual_return")
    a1 = row.get("year_1_alpha")

    parts = []

    if pd.notna(ar):
        parts.append(f"年化收益率 {_pct_of(ar)}")
        if row.get("is_return_good", False):
            parts.append(f"位于同类 {_rank_of(row, 'annual_return')}")
        else:
            parts.append("处于同类中游")

    if pd.notna(a1):
        if row.get("is_alpha_excellent", False):
            parts.append(f"年化超额 {_pct_of(a1)}，位于同类 {_rank_of(row, 'year_1_alpha')}，超额能力突出")
        elif row.get("is_alpha_good", False):
            parts.append(f"年化超额 {_pct_of(a1)}，超额能力居前")
        elif a1 > 0:
            parts.append(f"年化超额 {_pct_of(a1)}")
        elif a1 < 0 and row.get("is_return_good", False):
            # 超额为负但收益居前 → 市场环境拖累，相对表现尚可
            parts.append(f"年化超额 {_pct_of(a1)}，超额为负但同类排名相对居前，市场整体承压")
        elif a1 < 0:
            parts.append(f"年化超额 {_pct_of(a1)}，暂未展现明显优势")
        else:
            parts.append(f"年化超额接近零，增强特征不明显")

    if not parts:
        return "收益数据不足，暂不评价。"
    return "；".join(parts) + "。"


# ═══════════════════════════════════════════
#  ② Risk — 风险控制
# ═══════════════════════════════════════════

def _risk_summary(row) -> str:
    av = row.get("annual_volatility")
    mdd = row.get("max_drawdown")

    parts = []

    # 波动率
    if pd.notna(av):
        parts.append(f"年化波动率 {_pct_of(av)}")
        if row.get("is_vol_low", False):
            parts.append("波动率低于同类多数基金")
        elif row.get("is_vol_high", False):
            parts.append("波动率高于同类多数基金")

    # 最大回撤
    if pd.notna(mdd):
        parts.append(f"最大回撤 {_pct_of(mdd)}")
        if row.get("is_drawdown_low", False):
            parts.append(f"优于同类 {_better_than(row, 'max_drawdown')} 的基金")
        elif row.get("is_drawdown_worst", False):
            parts.append("高于同类多数基金，需关注下行风险")

    if not parts:
        return "风险数据暂缺，请重跑 03 以生成该指标。"
    return "；".join(parts) + "。"


# ═══════════════════════════════════════════
#  ③ Risk-Adjusted — 风险调整收益
# ═══════════════════════════════════════════

def _risk_adj_summary(row) -> str:
    sr = row.get("sharpe_ratio")
    cr = row.get("calmar_ratio")

    parts = []

    if pd.notna(sr):
        parts.append(f"Sharpe Ratio {sr:.2f}")
        if row.get("is_sharpe_good", False):
            parts.append("位于同类前列，风险调整收益较好")
        else:
            parts.append("处于同类中游")

    if pd.notna(cr):
        parts.append(f"Calmar Ratio {cr:.2f}")
        if row.get("is_calmar_good", False):
            parts.append("收益回撤比较高")

    if not parts:
        return "风险调整指标暂缺。"
    return "；".join(parts) + "。"


# ═══════════════════════════════════════════
#  ④ Consistency — 超额持续性
# ═══════════════════════════════════════════

def _consistency_summary(row) -> str:
    a1 = row.get("year_1_alpha")
    a6 = row.get("month_6_alpha")
    a1m = row.get("month_1_alpha")

    if pd.isna(a1):
        return "超额数据不足，持续性暂不评价。"

    a6_val = a6 if pd.notna(a6) else 0
    a1m_val = a1m if pd.notna(a1m) else 0
    EPS = TREND_TOLERANCE

    if a1 > 0 and a6_val > 0 and a1m_val > 0:
        if pd.notna(a6) and pd.notna(a1m):
            if max(abs(a1 - a6), abs(a6 - a1m), abs(a1 - a1m)) < EPS:
                return "一年、六月及一月均跑赢基准，各周期超额差异较小，超额持续性较好。"
        return "一年、六月及一月均跑赢基准，超额具有一定持续性。"

    if a1 <= 0 and a6_val <= 0 and a1m_val <= 0:
        return "各评价周期均未跑赢基准，超额持续性有待验证。"

    if pd.notna(a6) and pd.notna(a1m):
        if (a1m - a6 > EPS) and (a6 - a1 > EPS):
            return "超额收益呈逐期改善趋势，近期持续性向好。"
        if (a6 - a1m > EPS) and (a1 - a6 > EPS):
            if a1m <= 0:
                return "近期超额有所回落，持续性有待观察。"
            return "超额呈收敛趋势，但各周期仍保持正超额。"

    return "各周期超额存在波动，持续性一般。"


# ═══════════════════════════════════════════
#  ⑤ Summary — 综合画像
# ═══════════════════════════════════════════

def _summary_comment(row) -> str:
    profile = row.get("profile", "")
    summaries = {
        "稳健增强型": "超额能力与风险控制均衡，整体风险收益特征较优，可作为同类基金持续跟踪对象。",
        "风险收益优化型": "超额虽不突出但风险控制优秀，Sharpe及Calmar均居同类前列，风险调整后收益表现较优。",
        "高弹性增强型": "收益弹性较高，但波动/回撤偏高，适合风险承受能力较强的配置需求，需关注回撤控制能力。",
        "普通增强型": "风险收益特征处于同类中游，超额优势尚不突出，建议持续观察后续表现。",
        "指数复制型": "未展现显著的主动管理能力，收益与基准接近，增强效果不明显。",
        "观察样本": "成立时间较短，历史数据不足以进行完整的研究解读，暂不纳入比较。",
    }
    return summaries.get(profile, "")


# ═══════════════════════════════════════════
#  主入口
# ═══════════════════════════════════════════

def generate_summaries(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()

    df["return_summary"] = df.apply(_return_summary, axis=1)
    df["risk_summary"] = df.apply(_risk_summary, axis=1)
    df["risk_adj_summary"] = df.apply(_risk_adj_summary, axis=1)
    df["consistency_summary"] = df.apply(_consistency_summary, axis=1)
    df["summary_comment"] = df.apply(_summary_comment, axis=1)

    return df
