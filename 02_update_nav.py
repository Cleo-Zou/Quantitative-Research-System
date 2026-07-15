import os
import time
import pandas as pd
import akshare as ak

from config import (
    DATA_DIR,
    NAV_DIR,
    FUND_MASTER_PATH,
    REQUEST_DELAY,
    MAX_RETRIES,
)


def _format_seconds(sec: float) -> str:
    if sec < 60:
        return f"{sec:.0f}s"
    m, s = divmod(int(sec), 60)
    return f"{m}min{s}s"


def _find_col(df: pd.DataFrame, *candidates: str) -> str | None:
    for col in df.columns:
        col_str = str(col)
        for c in candidates:
            if c in col_str:
                return col
    return None


def ensure_dirs():
    log_dir = os.path.join(DATA_DIR, "log")
    for d in [DATA_DIR, NAV_DIR, log_dir]:
        os.makedirs(d, exist_ok=True)


def load_fund_master() -> list[str]:
    df = pd.read_parquet(FUND_MASTER_PATH)
    codes = df["fund_code"].astype(str).str.zfill(6).tolist()
    print(f"读取基金池: {FUND_MASTER_PATH}")
    print(f"共 {len(codes)} 只基金待更新\n")
    return codes


def fetch_fund_nav(fund_code: str) -> pd.DataFrame | None:
    for attempt in range(1 + MAX_RETRIES):
        try:
            df = ak.fund_open_fund_info_em(
                symbol=fund_code,
                indicator="单位净值走势",
            )

            if df is None or df.empty:
                return None

            date_col = _find_col(df, "净值日期", "日期", "date")
            unit_col = _find_col(df, "单位净值", "unit")
            acc_col = _find_col(df, "累计净值", "acc")
            adj_col = _find_col(df, "复权净值", "adj")

            if date_col is None:
                return None

            result = pd.DataFrame()
            result["date"] = pd.to_datetime(df[date_col]).dt.date

            if unit_col:
                result["unit_nav"] = pd.to_numeric(df[unit_col], errors="coerce")
            if acc_col:
                result["acc_nav"] = pd.to_numeric(df[acc_col], errors="coerce")
            if adj_col:
                result["adj_nav"] = pd.to_numeric(df[adj_col], errors="coerce")

            result["update_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
            result = result.dropna(subset=["date"])
            result = result.sort_values("date").reset_index(drop=True)
            return result

        except Exception:
            if attempt < MAX_RETRIES:
                time.sleep(REQUEST_DELAY * 2)

    return None


def load_existing_nav(fund_code: str) -> pd.DataFrame | None:
    path = os.path.join(NAV_DIR, f"{fund_code}.parquet")
    if not os.path.exists(path):
        return None
    df = pd.read_parquet(path)
    df["date"] = pd.to_datetime(df["date"]).dt.date
    return df


def save_nav(fund_code: str, df: pd.DataFrame):
    df = df.drop_duplicates(subset=["date"], keep="last")
    df = df.sort_values("date").reset_index(drop=True)
    path = os.path.join(NAV_DIR, f"{fund_code}.parquet")
    df.to_parquet(path, index=False)


def update_single_fund_nav(fund_code: str) -> dict:
    existing = load_existing_nav(fund_code)
    last_date = None if existing is None else existing["date"].max()

    fresh = fetch_fund_nav(fund_code)
    if fresh is None:
        return {"fund_code": fund_code, "status": "fail", "new": 0, "reason": "API"}

    now = time.strftime("%Y-%m-%d %H:%M:%S")

    if existing is None:
        merged = fresh
        new_count = len(fresh)
    else:
        if "update_time" not in existing.columns:
            existing["update_time"] = now
        if last_date is not None:
            new_data = fresh[fresh["date"] > last_date]
        else:
            new_data = fresh
        if new_data.empty:
            return {"fund_code": fund_code, "status": "ok", "new": 0, "reason": ""}
        merged = pd.concat([existing, new_data], ignore_index=True)
        new_count = len(new_data)

    save_nav(fund_code, merged)
    return {"fund_code": fund_code, "status": "ok", "new": new_count, "reason": ""}


def update_all_nav(fund_codes: list[str]) -> dict:
    total = len(fund_codes)
    ok_list: list[str] = []
    fail_list: list[str] = []
    total_new = 0
    t_start = time.time()

    for i, code in enumerate(fund_codes):
        pct = (i + 1) / total * 100
        elapsed = time.time() - t_start
        avg = elapsed / (i + 1) if i > 0 else REQUEST_DELAY
        eta = _format_seconds(avg * (total - i - 1))

        result = update_single_fund_nav(code)

        if result["status"] == "ok":
            ok_list.append(code)
            total_new += result["new"]
            tag = f"+{result['new']}" if result["new"] > 0 else " 不变"
        else:
            fail_list.append(code)
            tag = "失败"

        print(
            f"\r  [{i + 1:>4}/{total} {pct:>4.0f}%]  "
            f"✓{len(ok_list):>4}  ✗{len(fail_list):>3}  "
            f"剩余≈{eta:<8s}  "
            f"{code} {tag}",
            end="", flush=True,
        )

        time.sleep(REQUEST_DELAY)

    print()
    elapsed = time.time() - t_start
    return {
        "total": total,
        "ok": len(ok_list),
        "fail": len(fail_list),
        "total_new": total_new,
        "elapsed": elapsed,
        "fail_list": fail_list,
    }


def write_log(stats: dict):
    today = time.strftime("%Y%m%d")
    log_path = os.path.join(DATA_DIR, "log", f"nav_update_{today}.log")
    lines = [
        f"净值更新日志  {time.strftime('%Y-%m-%d %H:%M:%S')}",
        f"{'─' * 40}",
        f"基金总数: {stats['total']}",
        f"成功:     {stats['ok']}",
        f"失败:     {stats['fail']}",
        f"新增记录: {stats['total_new']}",
        f"耗时:     {_format_seconds(stats['elapsed'])}",
    ]
    if stats["fail_list"]:
        lines.append(f"{'─' * 40}")
        lines.append("失败基金:")
        for code in stats["fail_list"]:
            lines.append(f"  {code}")
    with open(log_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"\n日志已保存: {log_path}")


def main():
    print("\n" + "█" * 50)
    print("█  指数增强基金净值更新")
    print("█  数据来源: 天天基金 (via AKShare)")
    print("█" * 50)

    ensure_dirs()
    fund_codes = load_fund_master()

    if not fund_codes:
        print("基金池为空，请先运行 01_build_fund_pool.py")
        return

    total = len(fund_codes)
    eta = _format_seconds(total * REQUEST_DELAY)
    print(f"预计耗时 ≈ {eta}（{total} 只 × {REQUEST_DELAY}s）\n")

    stats = update_all_nav(fund_codes)

    print(f"\n{'─' * 40}")
    print(f"更新完成")
    print(f"  成功: {stats['ok']}")
    print(f"  失败: {stats['fail']}")
    print(f"  新增: {stats['total_new']} 条记录")
    print(f"  耗时: {_format_seconds(stats['elapsed'])}")
    print(f"{'─' * 40}")

    write_log(stats)

    print("\n" + "█" * 50)
    print("█  净值更新完成 ✓")
    print("█" * 50)


if __name__ == "__main__":
    main()
