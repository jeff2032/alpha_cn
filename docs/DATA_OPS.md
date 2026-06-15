# 数据运维手册

这个文件用于记录 A 股日线数据的日常维护流程。

每日选股研究流程见 [docs/DAILY_RESEARCH.md](G:/OwnProject/alpha_cn/docs/DAILY_RESEARCH.md)。

## 日期规则

A 股日线数据只能更新到最近一个交易日。

例如，2026-06-14 是周日，A 股没有交易，所以最近一个正常交易日是 2026-06-12。命令不能生成 2026-06-14 的日线 K 线，因为市场没有开盘。

## 检查是否全部下载

检查股票池里的每个标的是否都有本地 CSV 缓存：

```powershell
python -m quant_a_stock.cli cache-status --universe-file data/universe/a_stock.csv --show-missing --top 20 --output-missing data/universe/missing.csv
```

关键字段：

- `total`：股票池里的标的数量
- `cached`：已经有本地 CSV 的标的数量
- `missing`：还没有本地 CSV 的标的数量

如果 `missing > 0`，继续补下载：

```powershell
python -m quant_a_stock.cli sync-stock-universe --universe-file data/universe/a_stock.csv --since 2020-01-01 --stock-provider sina --adjust qfq --sleep 1.5 --skip-existing
```

## 检查数据日期覆盖

检查哪些标的没有更新到最近工作日：

```powershell
python -m quant_a_stock.cli cache-date-status --universe-file data/universe/a_stock.csv --show-stale --top 30 --output-stale data/universe/stale.csv
```

需要明确指定目标日期时：

```powershell
python -m quant_a_stock.cli cache-date-status --universe-file data/universe/a_stock.csv --target-date 2026-06-12 --show-stale --top 30 --output-stale data/universe/stale.csv
```

关键字段：

- `target_date`：希望本地缓存更新到的日期
- `fresh`：已经达到目标日期的标的数量
- `stale`：最后一根 K 线早于目标日期的标的数量
- `earliest_last` / `latest_last`：本地缓存最后日期的范围

## 只补过期标的

`cache-date-status` 会把过期标的写入 `data/universe/stale.csv`。然后只补这些标的：

```powershell
python -m quant_a_stock.cli sync-stock-universe --universe-file data/universe/stale.csv --since 2020-01-01 --stock-provider sina --adjust qfq --sleep 1.5 --no-skip-existing
```

这里使用 `--no-skip-existing`，因为这些标的已经有 CSV 文件，只是日期没更新到目标日期，需要覆盖刷新。

## 全量刷新

只有在明确想重拉整个股票池时才使用：

```powershell
python -m quant_a_stock.cli sync-stock-universe --universe-file data/universe/a_stock.csv --since 2020-01-01 --stock-provider sina --adjust qfq --sleep 1.5 --no-skip-existing
```

全量刷新耗时较长，也更容易给数据源造成压力。优先使用“只补过期标的”的方式。

## 断点续跑

如果批量下载中断，只想补缺失文件：

```powershell
python -m quant_a_stock.cli sync-stock-universe --universe-file data/universe/a_stock.csv --since 2020-01-01 --stock-provider sina --adjust qfq --sleep 1.5 --skip-existing
```

这个命令会跳过已有 CSV，继续下载缺失标的。

## 下载小股票池

下载几个个股：

```powershell
python -m quant_a_stock.cli sync-daily --symbols 688143 688146 600519 --since 2020-01-01 --asset-type stock --stock-provider sina --adjust qfq
```

使用 Sina 备用源下载 ETF：

```powershell
python -m quant_a_stock.cli sync-daily --symbols 510300 159915 510500 --since 2020-01-01 --asset-type etf --etf-provider sina --adjust none
```

## 扫描潜伏池和突破确认池

扫描所有缓存标的的突破确认池：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern base_breakout_setup --top 50 --min-score 50
```

只扫描更接近“突破确认”的候选：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern base_breakout_setup --top 50 --min-score 50 --stages watch near_breakout --min-amount-ma20 100000000 --require-positive-trend-slope --max-close-vs-trend 0.25 --filter-max-ret-20 0.25
```

扫描更接近“低位潜伏”的候选：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern accumulation_setup --top 120 --min-score 50 --stages accumulation --base-window 250 --max-base-range 0.45 --min-amount-ma20 100000000 --min-volume-ratio 1.05 --max-volume-ratio 2.20 --require-positive-trend-slope --max-close-vs-trend 0.12 --max-close-vs-cost 0.18 --filter-max-ret-20 0.15 --max-ret-60 0.30 --max-price-position 0.82
```

潜伏池现在会同时输出：

- `monthly_position_pct`：月线长期区间位置。
- `weekly_trend_slope_pct`：周线趋势斜率。
- `daily_score`、`weekly_score`、`monthly_score`：日/周/月拆分评分。
- `setup_phase`：长期低位蓄势、周线右侧启动、日线触发观察等节奏标签。

只扫描自选观察池：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern base_breakout_setup --symbols 688143 688146 600519 --top 20 --min-score 30 --include-extended
```

## 情绪面和市场主线

先跑形态扫描，再用最新扫描报告做情绪评分：

```powershell
python -m quant_a_stock.cli sentiment-score --latest-scan --target-date 2026-06-12 --top 20 --display-top 20 --news-days 7
```

如果只想看自选股：

```powershell
python -m quant_a_stock.cli sentiment-score --symbols 600160 601137 300568 --target-date 2026-06-12 --news-days 7
```

生成全市场主线观察报告：

```powershell
python -m quant_a_stock.cli market-theme --target-date 2026-06-12 --top 20
```

合成最终研究候选池：

```powershell
python -m quant_a_stock.cli research-candidates --target-date 2026-06-12 --top 30
```

回测研究候选池的技术代理版本：

```powershell
python -m quant_a_stock.cli research-backtest --years 2 --top-n 10 --rebalance-frequency W --min-score 50 --min-amount-ma20 100000000 --max-close-vs-trend 0.25 --filter-max-ret-20 0.25
```

这个回测只验证“历史形态 + 量价筛选”有没有收益倾向，不使用当前情绪接口回看过去。完整的“情绪 + 主线”历史回测需要先把每日新闻、热门关键词、涨停池、强势股池、公告风险和市场主线缓存成历史快照。

扫描参数组合：

```powershell
python -m quant_a_stock.cli research-optimize --years 2 --top-ns 5,10,20 --min-scores 45,50,55 --max-ret-20s 0.15,0.20,0.25 --rebalance-frequencies W M --min-amount-ma20 100000000 --max-close-vs-trend 0.25
```

当前较稳的技术代理参数：

```powershell
python -m quant_a_stock.cli research-backtest --years 2 --top-n 20 --rebalance-frequency M --min-score 45 --min-amount-ma20 100000000 --max-close-vs-trend 0.25 --filter-max-ret-20 0.15
```

归档每日研究快照：

```powershell
python -m quant_a_stock.cli snapshot-research --target-date 2026-06-12
```

生成每日中文复盘报告：

```powershell
python -m quant_a_stock.cli daily-research-summary --target-date 2026-06-12 --top 30
```

当前情绪面主要看：

- 东财人气排名
- 近端新闻数量
- 正向关键词和风险关键词
- 个股热门关键词
- 是否进入涨停池或强势股池

综合研究候选池会额外看：

- 上市天数：次新股会单独识别，避免和成熟样本混排。
- 量能过热：短期量能过大时扣分，降低追高风险。
- 涨幅过热：近 20 日涨幅过大时扣分。
- 主线命中：热门关键词或行业命中当日强主线时加分。
- 行业同涨：同一行业或同一主线里多只票同时进入形态池时加分。
- 风险公告：公告标题命中问询、处罚、立案、诉讼、减持、质押、担保逾期等关键词时扣分。

使用方式建议：

- 先用 `scan-pattern --pattern accumulation_setup` 找“长平台 + 低热度 + 温和放量”的潜伏池。
- 再用 `scan-pattern --pattern base_breakout_setup` 保留“接近突破确认”的辅助池。
- 再用 `sentiment-score` 看候选股有没有热度、新闻和概念承接。
- 最后用 `market-theme` 看候选是否落在当日强主线里。
- 用 `research-candidates` 汇总成最终观察池，优先复盘 A/B 级候选。
- 用 `daily-research-summary` 看当天主报告，它会合并市场温度、主题簇、候选持续性和风险提醒。
- 如果形态很好但情绪极弱，先放观察池；如果情绪很热但形态已经大幅加速，避免追高。

## 报告位置

运维和研究报告会写到 `reports/`。

常见报告文件：

- `sync_stock_universe_*.csv`
- `scan_accumulation_setup_*.csv`
- `scan_base_breakout_setup_*.csv`
- `sentiment_watchlist_*.csv`
- `sentiment_watchlist_*.md`
- `market_theme_*.csv`
- `market_theme_*.md`
- `research_candidates_*.csv`
- `research_candidates_*.md`
- `daily_research_candidates_*.csv`
- `daily_research_summary_*.md`
- `research_backtest_*.csv`
- `research_backtest_yearly_*.csv`
- `research_backtest_holdings_*.csv`
- `research_backtest_candidates_*.csv`
- `research_optimize_*.csv`
- `backtest_*.csv`
- `validate_*.csv`

`reports/` 已经被 git 忽略。
`data/snapshots/` 也被 git 忽略，用来保存每日研究快照。
