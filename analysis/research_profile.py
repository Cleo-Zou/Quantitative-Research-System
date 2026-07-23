import pandas as pd

from config import (
    ALPHA_NEUTRAL,
)


def determine_profile(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    profiles = []

    for _, row in df.iterrows():
        launch = row.get("launch_date")
        if pd.notna(launch) and str(launch) not in ("", "nan", "None"):
            try:
                launch_ts = pd.Timestamp(str(launch))
                days_since_launch = (pd.Timestamp.now() - launch_ts).days
                if days_since_launch < 365:
                    profiles.append("观察样本")
                    continue
            except Exception:
                pass

        a1 = row.get("year_1_alpha")
        if pd.isna(a1):
            profiles.append("观察样本")
            continue

        a6 = row.get("month_6_alpha")
        a1m = row.get("month_1_alpha")
        a6_val = a6 if pd.notna(a6) else 0
        a1m_val = a1m if pd.notna(a1m) else 0

        is_excellent = row.get("is_alpha_excellent", False)
        is_sharpe_good = row.get("is_sharpe_good", False)
        is_calmar_good = row.get("is_calmar_good", False)
        is_vol_low = row.get("is_vol_low", False)
        is_vol_high = row.get("is_vol_high", False)
        is_drawdown_worst = row.get("is_drawdown_worst", False)
        is_return_good = row.get("is_return_good", False)

        # ── 指数复制型 ──
        if a1 <= 0 and a6_val <= 0 and a1m_val <= 0:
            profiles.append("指数复制型")
            continue

        # ── Alpha 全周期为正 + 超额突出 → 看风险维度 ──
        if is_excellent and a1 > 0 and a6_val > 0 and a1m_val > 0:
            if is_vol_high or is_drawdown_worst:
                profiles.append("高弹性增强型")
            else:
                profiles.append("稳健增强型")
            continue

        # ── 风险收益优化型: Sharpe + Calmar 双高 + 低波动（即使 Alpha 不突出）──
        if is_sharpe_good and is_calmar_good and is_vol_low:
            profiles.append("风险收益优化型")
            continue

        # ── 稳健增强型: Alpha 正 + 至少一个风险指标好 ──
        if a1 > 0 and a6_val > 0 and a1m_val > 0:
            if is_vol_high or is_drawdown_worst:
                profiles.append("高弹性增强型")
            else:
                profiles.append("稳健增强型")
            continue

        # ── 超额突出但部分周期不完美 → 区分弹性 ──
        if is_excellent:
            if is_vol_high or is_drawdown_worst:
                profiles.append("高弹性增强型")
            else:
                profiles.append("稳健增强型")
            continue

        # ── 收益高但 Alpha 一般 + 高波动/回撤 → 弹性型 ──
        if is_return_good and (is_vol_high or is_drawdown_worst):
            profiles.append("高弹性增强型")
            continue

        # ── Alpha 接近零 → 普通 ──
        if abs(a1) < ALPHA_NEUTRAL:
            profiles.append("普通增强型")
            continue

        # ── 兜底 ──
        profiles.append("普通增强型")

    df["profile"] = profiles
    return df
