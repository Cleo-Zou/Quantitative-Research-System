
# 指数增强基金量化研究系统

> **Quantitative Research System for Enhanced Index Funds**

[![Daily Update](https://github.com/Cleo-Zou/Quantitative-Research-System/actions/workflows/daily-update.yml/badge.svg)](https://github.com/Cleo-Zou/Quantitative-Research-System/actions/workflows/daily-update.yml)

一套完整的指数增强基金量化研究系统，覆盖基金池构建、净值采集、收益计算、五核心风险指标评估、研究解读自动生成与可视化展示的全流程。基于 **Rule-based Research Interpretation Engine**，自动生成基金画像（Profile）、研究标签（Tags）和五段研究摘要（Research Summary）。

A complete quantitative research system for enhanced index funds — covering fund pool construction, NAV collection, return/risk calculation, automated research interpretation, and visualization. Powered by a **Rule-based Research Interpretation Engine**.

---

## 研究范围 / Research Scope

| 基准指数 Benchmark | 增强基金数量 Count | 代码 Codes |
|---|---|---|
| 沪深300 (CSI 300) | ~190 | HS300 |
| 中证500 (CSI 500) | ~310 | ZZ500 |
| 中证1000 (CSI 1000) | ~90 | ZZ1000 |
| 中证全指 (CSI All-Share) | ~25 | CSI_ALL |

---

## 五核心评价指标 / Five Core Metrics

| 指标 Metric | 公式 Formula | 方向 |
|---|---|---|
| **年化收益率** Annual Return | $(NAV_{end}/NAV_{start})^{252/N}-1$ | ↑ |
| **年化波动率** Annual Volatility | $\sigma_{daily} \times \sqrt{252}$ | ↓ |
| **夏普比率** Sharpe Ratio | $(R_{annual}-R_f)/\sigma_{annual}$ | ↑ |
| **最大回撤** Max Drawdown | $\min(NAV_t/Peak_t - 1)$ | ↓ |
| **卡玛比率** Calmar Ratio | $R_{annual}/|MDD|$ | ↑ |

加上 3 个周期的 Alpha（近一月 / 近六月 / 近一年）。

Plus 3-period Alpha (1M / 6M / 1Y).

---

## 系统架构 / Architecture

```
                          AKShare / 天天基金
                                │
        ┌───────────────────────┼───────────────────────┐
        ▼                       ▼                       ▼
  01_build_fund_pool    02_update_nav         03_calculate_return
  基金池构建             净值采集               收益 & 风险指标
  fund_master.parquet   data/nav/*.parquet    excess_return.parquet
        │                       │                       │
        └───────────────────────┼───────────────────────┘
                                │
                    ┌───────────┼───────────┐
                    ▼           ▼           ▼
              04 绩效看板   05 Excel   06 研究看板
              index.html  analysis   research.html
                          .xlsx
                    │           │           │
                    └───────────┼───────────┘
                                ▼
                           output/
                                │
                                ▼
                         GitHub Pages
```

---

## 研究解读引擎 / Research Interpretation Engine

### Six Profiles（六类基金画像）

| Profile | 英文 English | 特征 Characteristics |
|---------|-------------|---------------------|
| 稳健增强型 | Stable Enhanced | Alpha > 0, Sharpe/Calmar top, low drawdown |
| 风险收益优化型 | Risk-Return Optimized | High Sharpe + Calmar, low volatility, moderate Alpha |
| 高弹性增强型 | High-Elastic Enhanced | High return/Alpha but high vol/drawdown |
| 普通增强型 | Standard Enhanced | Middle of the pack |
| 指数复制型 | Index-Replicating | Alpha ≤ 0 across all periods |
| 观察样本 | Observation Sample | Listed < 1 year, insufficient data |

### Research Tags（研究标签）

`[持续跑赢]` `[超额突出]` `[Alpha稳定]` `[短期改善]` `[近期回落]` `[高收益]` `[低波动]` `[高Sharpe]` `[高Calmar]` `[低回撤]`

### Five-Step Summary（五段研究摘要）

1. **收益能力 Return** — Annual Return + Alpha
2. **风险控制 Risk** — Volatility + Max Drawdown
3. **风险调整收益 Risk-Adjusted** — Sharpe + Calmar
4. **超额持续性 Consistency** — Alpha trend across 3 periods
5. **综合画像 Summary** — Profile conclusion

---

## 快速开始 / Quick Start

### 安装 / Install

```bash
pip install -r requirements.txt
```

### 运行完整流水线 / Run Full Pipeline

```bash
python 01_build_fund_pool1.py      # 1/6 构建基金池
python 02_update_nav.py            # 2/6 更新净值
python 03_calculate_return.py      # 3/6 计算收益与风险指标
python 04_generate_html.py         # 4/6 生成绩效看板
python 05_export_analysis.py       # 5/6 生成研究 Excel
python 06_generate_research_html.py # 6/6 生成研究看板
```

### 一键运行 / One-Click

```bash
# Windows
run_daily.bat

# 自动静默运行（适合定时任务）
run_scheduled.bat
```

---

## 自动化部署 / Automated Deployment

**GitHub Actions** 每个工作日 18:00（北京时间）自动触发，跑完全部六步后将结果部署到 **GitHub Pages**。

Scheduled workflow runs every weekday at 18:00 CST (UTC 10:00), executes all 6 steps, and deploys to GitHub Pages.

### 输出产物 / Outputs

| 产物 Output | 路径 Path | 说明 Description |
|------------|----------|-----------------|
| 绩效看板 | `output/index.html` | 交互式表格 + ECharts 走势图 |
| 研究看板 | `output/research.html` | 五核心指标 + Profile + Tags |
| 研究分析 | `output/research_analysis.xlsx` | 四个 Benchmark Sheet + 汇总 |

---

## 项目结构 / Project Structure

```
Index_Enhancement_Monitor/
├── 01_build_fund_pool1.py      # 基金池构建 Fund pool
├── 02_update_nav.py            # 净值采集 NAV collection
├── 03_calculate_return.py      # 收益 & 风险计算 Returns & risk
├── 04_generate_html.py         # 绩效 HTML Performance dashboard
├── 05_export_analysis.py       # 研究 Excel Research Excel
├── 06_generate_research_html.py # 研究 HTML Research dashboard
├── config.py                   # 全局配置 Global config
├── utils.py                    # 公共工具 Utilities
├── analysis/                   # 研究解读引擎 Research engine
│   ├── ranking.py              #   同类排名 Ranking
│   ├── research_profile.py     #   画像判定 Profile
│   ├── research_tags.py        #   标签生成 Tags
│   ├── research_summary.py     #   摘要拼装 Summary
│   └── excel.py                #   Excel 导出 Export
├── data/                       # 数据缓存 Data cache
│   ├── nav/                    #   净值文件 NAV files
│   ├── return/                 #   收益数据 Return data
│   ├── index/                  #   指数行情 Index prices
│   └── fund_master.parquet     #   基金主表 Fund master
├── output/                     # 输出产物 Outputs
├── docs/                       # 文档 Documentation
│   ├── evaluation-methodology.md  # 评价方法论
│   └── project_report.md          # 项目报告
├── .github/workflows/          # CI/CD
│   └── daily-update.yml        #   每日自动更新
├── run_daily.bat               # Windows 一键运行
├── run_scheduled.bat           # Windows 静默运行
├── requirements.txt            # Python 依赖
└── README.md                   # 本文件 This file
```

---

## 技术栈 / Tech Stack

| 层级 Layer | 技术 Technology |
|-----------|---------------|
| 数据源 Data | AKShare, 中证指数公司 CSI |
| 计算 Engine | Python 3.12, NumPy, Pandas |
| 研究引擎 Research | Rule-based Engine (自研) |
| 可视化 Viz | xlsxwriter (Excel), ECharts + Vanilla JS (HTML) |
| 自动化 CI/CD | GitHub Actions |
| 部署 Deploy | GitHub Pages |

---

## 设计原则 / Design Principles

1. **同类比较 Like-for-Like**: 所有评价仅在相同 Benchmark 基金之间完成
2. **超额优先 Alpha First**: Alpha 代表主动管理能力，是评价核心
3. **持续性优先 Consistency over Burst**: 稳定超额比一次性爆发更有价值
4. **风险匹配 Risk-Adjusted**: Alpha 必须建立在合理风险水平之上
5. **可解释性 Explainability**: 每条结论可追溯至明确数据与确定性规则

---

## License

MIT
