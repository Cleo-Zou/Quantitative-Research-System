import pandas as pd

from config import (
    ALPHA_NEUTRAL,
    TREND_TOLERANCE,
    ALPHA_EXCELLENT_ABS,
    ALPHA_GOOD_ABS,
    ALPHA_WEAK_ABS,
)


def determine_tags(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    statuses = []
    all_tags: list[str] = []

    for _, row in df.iterrows():
        profile = row.get("profile", "")
        is_small = row.get("is_small_sample", False)
        tags = []

        # ── 第一层：状态标签 ──
        if profile == "观察样本":
            statuses.append("[观察样本]")
            all_tags.append("数据不足")
            continue
        else:
            statuses.append("正常")

        a1 = row.get("year_1_alpha")
        a6 = row.get("month_6_alpha")
        a1m = row.get("month_1_alpha")
        a6_val = a6 if pd.notna(a6) else 0
        a1m_val = a1m if pd.notna(a1m) else 0

    
        #  核心五维标签

        # 高收益
        if row.get("is_return_good", False):
            tags.append("[高收益]")

        # 低波动 / 高波动
        if row.get("is_vol_low", False):
            tags.append("[低波动]")
        elif row.get("is_vol_high", False):
            tags.append("[高波动]")

        # 高Sharpe
        if row.get("is_sharpe_good", False):
            tags.append("[高Sharpe]")

        # 高Calmar
        if row.get("is_calmar_good", False):
            tags.append("[高Calmar]")

        # 低回撤 / 高回撤
        if row.get("is_drawdown_low", False):
            tags.append("[低回撤]")
        elif row.get("is_drawdown_worst", False):
            tags.append("[高回撤]")

        #  Alpha 标签
        if pd.notna(a1):
            # 持续跑赢: 各周期全部 > 0
            if a1 > 0 and a6_val > 0 and a1m_val > 0:
                tags.append("[持续跑赢]")

            # Alpha 稳定: 三个周期中至少两个 Alpha > 0（胜率法）
            if pd.notna(a1):
                alphas = [a for a in [a1, a6, a1m] if pd.notna(a)]
                positive = sum(1 for a in alphas if a > 0)
                if positive >= 2:
                    tags.append("[Alpha稳定]")

            # 超额突出: IR ≥ 1.0（单位主动风险换取 1 单位以上超额）
            ir = row.get("information_ratio")
            if pd.notna(ir) and ir >= 1.0:
                tags.append("[超额突出]")

            # 短期改善
            if pd.notna(a6) and pd.notna(a1m):
                if (a1m - a6 > TREND_TOLERANCE) and (a6 - a1 > TREND_TOLERANCE):
                    tags.append("[短期改善]")

            # 近期回落
            if pd.notna(a6) and pd.notna(a1m):
                if (a6 - a1m > TREND_TOLERANCE) and (a1 - a6 > TREND_TOLERANCE) and a1m <= 0:
                    tags.append("[近期回落]")

            # 超额偏弱
            if abs(a1) < ALPHA_NEUTRAL:
                tags.append("[超额偏弱]")

            # 超额落后
            if a1 < 0:
                if row.get("is_alpha_weak", False) or (is_small and a1 < ALPHA_WEAK_ABS):
                    tags.append("[超额落后]")

        # ── 兜底 ──
        if len(tags) == 0:
            tags.append("[表现居中]")

        all_tags.append("  ".join(tags))

    df["status"] = statuses
    df["tags"] = all_tags
    return df
