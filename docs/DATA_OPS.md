# 数据运维手册

这个文件用于记录 A 股日线数据的日常维护流程。

每日选股研究流程见 [docs/DAILY_RESEARCH.md](G:/OwnProject/alpha_cn/docs/DAILY_RESEARCH.md)。

## 日期规则

A 股日线数据只能更新到最近一个交易日。

例如，2026-06-14 是周日，A 股没有交易，所以最近一个正常交易日是 2026-06-12。命令不能生成 2026-06-14 的日线 K 线，因为市场没有开盘。

注意：不要只按周一到周五判断。端午、春节、国庆等交易所休市日也要避开。项目会优先根据本地全市场缓存推断真实交易日；如果传入的是节假日或非交易日，会自动回退到最近一个已缓存交易日。

## 刷新股票池

先刷新股票池，避免旧股票池漏掉能下载的标的：

```powershell
python -m quant_a_stock.cli refresh-stock-universe --existing-file data/universe/a_stock.csv --output data/universe/a_stock.csv --manual-files config/required_symbols.csv
```

`refresh-stock-universe` 会合并旧股票池、多个在线数据源和 `config/required_symbols.csv`。某个在线数据源失败时，默认保留旧股票池继续，不会因为接口波动把已有标的删掉。

你临时重点研究的票，可以加到 `config/required_symbols.csv`，后续夜间补数会强制纳入股票池。原则是：只要数据源能下载，就不能因为股票池旧、代码漏或单次接口失败而长期漏数。

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
python -m quant_a_stock.cli sync-stock-universe --universe-file data/universe/a_stock.csv --since 2020-01-01 --stock-provider sina --adjust qfq --workers 2 --sleep 0.05 --skip-existing
```

如果出现大量 `RemoteDisconnected('Remote end closed connection without response')`，通常不是个股问题，而是数据源被全市场高频请求打断或临时限流。处理方式：

```powershell
python -m quant_a_stock.cli sync-stock-universe --universe-file data/universe/stale.csv --since 2020-01-01 --stock-provider eastmoney --adjust qfq --incremental --lookback-days 60 --workers 1 --sleep 0.3 --retries 3 --retry-wait 2 --max-consecutive-failures 40 --no-skip-existing
```

日常脚本已经内置保护：Sina 自动降到 1 线程，Eastmoney 自动降到 2 线程，最小请求间隔 0.2 秒，并在连续失败过多时提前停止，避免刷出几千条失败日志。

## 检查数据日期覆盖

检查哪些标的没有更新到最近交易日：

```powershell
python -m quant_a_stock.cli cache-date-status --universe-file data/universe/a_stock.csv --show-stale --top 30 --output-stale data/universe/stale.csv
```

需要明确指定目标日期时：

```powershell
python -m quant_a_stock.cli cache-date-status --universe-file data/universe/a_stock.csv --target-date 2026-06-12 --show-stale --top 30 --output-stale data/universe/stale.csv
```

如果指定日期不是本地缓存中的交易日，命令会提示并回退。例如节假日传入 `2026-06-19` 时，会使用最近一个已缓存交易日，而不是误判所有股票都缺数据。

如果是在收盘后准备补当天数据，且当天还没有任何标的落到缓存里，用精确目标日检查：

```powershell
python -m quant_a_stock.cli cache-date-status --universe-file data/universe/a_stock.csv --target-date 2026-06-22 --exact-target-date --show-stale --top 30 --output-stale data/universe/stale.csv
```

关键字段：

- `target_date`：希望本地缓存更新到的日期
- `fresh`：已经达到目标日期的标的数量
- `stale`：最后一根 K 线早于目标日期的标的数量
- `earliest_last` / `latest_last`：本地缓存最后日期的范围

## 只补过期标的

`cache-date-status` 会把过期标的写入 `data/universe/stale.csv`。然后只补这些标的：

```powershell
python -m quant_a_stock.cli sync-stock-universe --universe-file data/universe/stale.csv --since 2020-01-01 --stock-provider sina --adjust qfq --incremental --lookback-days 60 --workers 2 --sleep 0.05 --no-skip-existing
```

这里使用 `--incremental`，因为这些标的已经有 CSV 文件，只是日期没更新到目标日期。程序会从本地最后日期往前回看 `--lookback-days` 个自然日，只刷新最近一段数据，再和旧缓存合并去重。

日常推荐 `--lookback-days 60`：速度更快，适合每天收盘后补数据、出候选池。周末或月末想更稳地刷新 250 日平台指标和最近复权，可以临时改成 `--lookback-days 450`。需要更严格重算月线三年结构时，可以临时改成 `--lookback-days 1200`。

`--workers` 控制并行下载线程数。日常默认入口可以给 `--workers 6`，但脚本会把 `sina` 自动保护到 2，避免 AKShare 依赖里的 `py_mini_racer` 在高并发下崩溃。现在 `run_data_sync.ps1` 会先用 `sina` 补数；如果主源进程崩溃或失败，会重新生成过期清单，再用 `eastmoney` 备用源继续补剩余标的。最后统一用覆盖率检查判断是否还需要重试。

也可以直接用数据补数脚本，它会自动生成过期清单、并行补数、最后再检查一次覆盖率：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_data_sync.ps1
```

明确指定目标日和备用源：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_data_sync.ps1 -TargetDate 2026-06-25 -StockProvider sina -FallbackStockProvider eastmoney -Workers 6 -FallbackWorkers 6
```

后台运行时使用：

```powershell
Start-Process powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$PWD\scripts\run_data_sync.ps1`"" -WindowStyle Hidden
```

日志在 `logs/data_sync/`。

## 全量刷新

只有在明确想重拉整个股票池时才使用：

```powershell
python -m quant_a_stock.cli sync-stock-universe --universe-file data/universe/a_stock.csv --since 2020-01-01 --stock-provider sina --adjust qfq --workers 2 --sleep 0.1 --no-skip-existing
```

全量刷新会从 `--since` 开始重拉整个股票池，耗时很长，也更容易给数据源造成压力。日常不要用它，优先使用“只补过期标的 + `--incremental`”。

## 断点续跑

如果批量下载中断，只想补缺失文件：

```powershell
python -m quant_a_stock.cli sync-stock-universe --universe-file data/universe/a_stock.csv --since 2020-01-01 --stock-provider sina --adjust qfq --workers 2 --sleep 0.05 --skip-existing
```

这个命令会跳过已有 CSV，继续下载缺失标的。

如果是当天数据中断，优先重新生成过期清单，然后只补 `stale.csv`：

```powershell
python -m quant_a_stock.cli cache-date-status --universe-file data/universe/a_stock.csv --show-stale --top 30 --output-stale data/universe/stale.csv
python -m quant_a_stock.cli sync-stock-universe --universe-file data/universe/stale.csv --since 2020-01-01 --stock-provider sina --adjust qfq --incremental --lookback-days 60 --workers 2 --sleep 0.05 --no-skip-existing
```

跑一段时间后，用下面这个命令看还剩多少没补到目标日期：

```powershell
python -m quant_a_stock.cli cache-date-status --universe-file data/universe/a_stock.csv --show-stale --top 20 --output-stale data/universe/stale.csv
```

## 下载小股票池

下载几个个股：

```powershell
python -m quant_a_stock.cli sync-daily --symbols 688143 688146 600519 --since 2020-01-01 --asset-type stock --stock-provider sina --adjust qfq --incremental --lookback-days 60
```

下载 ETF/指数温度池：

```powershell
python -m quant_a_stock.cli sync-daily --symbols 510300 510500 159915 --since 2020-01-01 --asset-type etf --etf-provider eastmoney --adjust none --incremental --lookback-days 60
python -m quant_a_stock.cli cache-date-status --symbols 510300 510500 159915 --target-date 2026-06-23 --exact-target-date --show-stale --top 10
```

如果 Eastmoney ETF 源报 `RemoteDisconnected` 或日期没有补到目标日，用 Sina 备用源重试：

```powershell
python -m quant_a_stock.cli sync-daily --symbols 510300 510500 159915 --since 2020-01-01 --asset-type etf --etf-provider sina --adjust none --incremental --lookback-days 60
```

## 扫描潜伏池、突破确认池和趋势回踩池

扫描所有缓存标的的突破确认池：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern base_breakout_setup --top 50 --min-score 50
```

只扫描更接近“突破确认”的候选：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern base_breakout_setup --top 160 --min-score 45 --stages watch near_breakout --min-amount-ma20 100000000 --require-positive-trend-slope --max-close-vs-trend 0.25 --filter-max-ret-20 0.25
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

扫描“强趋势回踩/再启动”的补充候选：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern trend_pullback_setup --top 160 --min-score 45 --stages trend_pullback trend_resume --min-amount-ma20 100000000 --min-ret-60 0.18 --filter-max-ret-20 0.18 --max-volume-ratio 3.20 --max-close-vs-trend 0.65 --max-drawdown-from-high 0.32
```

趋势回踩池会输出：

- `ret_60_pct`：60 日趋势强度。
- `drawdown_from_high_pct`：离近 60 日高点的回撤。
- `trend_score`、`pullback_score`、`resume_score`：趋势、回踩和再启动拆分评分。

只扫描自选观察池：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern base_breakout_setup --symbols 688143 688146 600519 --top 20 --min-score 30 --include-extended
```

## 情绪面和市场主线

先跑形态扫描，再用最新扫描报告做情绪评分：

```powershell
python -m quant_a_stock.cli sentiment-score --latest-scan --target-date 2026-06-12 --top 90 --display-top 30 --news-days 7
```

如果只想看自选股：

```powershell
python -m quant_a_stock.cli sentiment-score --symbols 600160 601137 300568 --target-date 2026-06-12 --news-days 7
```

生成全市场主线观察报告：

```powershell
python -m quant_a_stock.cli market-theme --target-date 2026-06-12 --top 20
```

生成东财资金流确认因子：

```powershell
python -m quant_a_stock.cli money-flow --latest-scan --target-date 2026-06-12 --top 90 --lookback-days 10 --display-top 30 --retries 3 --retry-wait 2 --sleep 0.4 --min-success-rate 0.6
```

资金流是增强确认源，东财接口偶尔会断连。默认成功率低于阈值时不会写正式 `money_flow_*.csv`，避免把大量失败行并入候选池；夜间任务使用 `--soft-fail`，低成功率只记录警告，不阻塞后续候选池、快照和复盘。

生成巨潮结构化公告风险事件：

```powershell
python -m quant_a_stock.cli risk-events --latest-scan --target-date 2026-06-12 --top 90 --days 180 --display-top 30
```

导入问财人工条件选股结果：

```powershell
python -m quant_a_stock.cli import-iwencai --file exports/iwencai/2026-06-12.csv --target-date 2026-06-12 --query "低位放量 半导体"
```

这些增强报告只按同一 `target-date` 自动合并，不会用其他日期兜底。资金流只做确认加分；问财只做外部条件验证；巨潮风险事件会进入风险扣分和 `risk_tags`，优先级高于资金和情绪。

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
- 巨潮风险事件：结构化识别退市/ST、立案处罚、监管问询、财务审计风险、业绩风险、减持解禁、质押冻结、诉讼仲裁等事件，高风险事件会直接压制候选。
- 资金流确认：东财个股资金流转成 `money_flow_score`，只做小幅确认加分；连续主力流出会进入风险标签。
- 问财外部验证：人工导出的问财条件选股结果转成 `iwencai_hit/iwencai_score`，只做外部验证，不替代模型主信号。
- 动作分组：`action_bucket` 会把候选拆成主攻、升级观察和风险回避。当前主攻只保留 A2 启动确认和主线仍强、风险干净、不拥挤的 A3 趋势延续；A1 先观察；B2 拆成 `观察-B2a主线扩散待升级`、`观察-B2s主线突发待确认` 和 `观察-B2b主题待确认`，不直接当买点。
- 风险标签：`risk_level` 和 `risk_tags` 要优先看，公告风险、次新样本不足、成交额偏低、涨幅/量能过热会明显降权。

使用方式建议：

- 先用 `scan-pattern --pattern accumulation_setup` 找“长平台 + 低热度 + 温和放量”的潜伏池。
- 再用 `scan-pattern --pattern base_breakout_setup` 保留“接近突破确认”的辅助池。
- 再用 `scan-pattern --pattern trend_pullback_setup` 补充“强趋势回踩/再启动”的 A3 池。
- 再用 `sentiment-score` 看候选股有没有热度、新闻和概念承接。
- 最后用 `market-theme` 看候选是否落在当日强主线里。
- 夜间慢准备里用 `money-flow`、`risk-events` 和 `import-iwencai` 增强资金确认、公告风险和外部条件验证。
- 用 `research-candidates` 汇总成最终观察池，优先复盘 `action_bucket` 里的主攻池、B2a 主线扩散升级观察池、B2s 低位主线突发待确认池和 B2b 主题待确认池。
- 用 `daily-research-summary` 看当天主报告，它会合并市场温度、主题簇、候选持续性和风险提醒。
- 如果形态很好但情绪极弱，先放观察池；如果情绪很热但形态已经大幅加速，避免追高。

## 研究仓库

数据闭环和保留策略见 `docs/DATA_LIFECYCLE.md`。日常可以用：

```powershell
.\scripts\alpha.ps1 data-loop
.\scripts\alpha.ps1 retention-plan
```

每日报告生成后，把最新结果写入 DuckDB + Parquet：

```powershell
python -m quant_a_stock.cli warehouse-ingest --target-date 2026-06-18 --plan-date 2026-06-19
```

这一步会同时派生中间层事实表：`run_manifest`、`data_quality_daily`、`research_candidate_daily`、`stock_market_attitude_daily`、`risk_event_daily`、`money_flow_daily`、`external_screen_daily`、`missed_opportunity_daily`、`factor_diagnostics_daily`、`strategy_review_daily`。同一天重复跑会覆盖同日分区，不会把行数翻倍。

早上先看运行清单和数据质量：

```powershell
python -m quant_a_stock.cli warehouse-query --table run_manifest --columns run_id,target_date,plan_date,quality_status,missing_required,warning_reports --limit 5
python -m quant_a_stock.cli warehouse-query --table data_quality_daily --columns target_date,source_group,report_type,quality_level,issue --since 2026-06-18 --until 2026-06-18 --limit 50
```

查询候选池中间层：

```powershell
python -m quant_a_stock.cli warehouse-query --table research_candidate_daily --columns target_date,symbol,name,tier,action_bucket,research_score,candidate_model_version --since 2026-06-18 --limit 30
```

把股票池写入维表：

```powershell
python -m quant_a_stock.cli warehouse-sync-universe --universe-file data/universe/a_stock.csv --target-date 2026-06-18
```

把本地日线 CSV 缓存同步为 Parquet：

```powershell
python -m quant_a_stock.cli warehouse-sync-candles --universe-file data/universe/a_stock.csv --target-date 2026-06-18
```

行情同步会先比较本地 CSV 最后日期和仓库索引，已同步的标的会跳过；第一次初始化会慢，后续夜间会快很多。只想试跑少量标的可以用：

```powershell
python -m quant_a_stock.cli warehouse-sync-candles --symbols 000001 002137 600999 --target-date 2026-06-18
```

回填历史研究快照：

```powershell
python -m quant_a_stock.cli warehouse-backfill-snapshots --since 2026-06-12 --until 2026-06-18
```

这一步会从历史快照派生 `research_candidate_daily` 和 `stock_market_attitude_daily`，用于长期复盘和因子挖掘。

查看仓库状态：

```powershell
python -m quant_a_stock.cli warehouse-status
```

按日期区间做复盘汇总：

```powershell
python -m quant_a_stock.cli warehouse-review --since 2026-06-12 --until 2026-06-18
```

仓库路径：

- DuckDB：`data/warehouse/alpha_cn.duckdb`
- Parquet：`data/warehouse/parquet/`

研究报告和快照入库是按目标交易日覆盖的。同一天重复跑不会把行数翻倍，只保留最新一版报告结果。日线行情按股票代码覆盖。这个目录不提交 git。

## 报告位置

运维和研究报告会写到 `reports/`。

常见报告文件：

- `sync_stock_universe_*.csv`
- `scan_accumulation_setup_*.csv`
- `scan_base_breakout_setup_*.csv`
- `scan_trend_pullback_setup_*.csv`
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
