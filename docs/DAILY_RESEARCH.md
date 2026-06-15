# 每日选股研究流程

这个流程用于每天收盘后做 A 股候选池研究。目标是选出少量值得人工复盘的股票，而不是直接生成买卖指令。

## 每天固定流程

先确认数据是否更新到最近交易日：

```powershell
python -m quant_a_stock.cli cache-date-status --universe-file data/universe/a_stock.csv --show-stale --top 30 --output-stale data/universe/stale.csv
```

如果有过期标的，只补过期标的：

```powershell
python -m quant_a_stock.cli sync-stock-universe --universe-file data/universe/stale.csv --since 2020-01-01 --stock-provider sina --adjust qfq --sleep 1.5 --no-skip-existing
```

扫描全市场突破确认池：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern base_breakout_setup --top 120 --min-score 50 --stages watch near_breakout --min-amount-ma20 100000000 --require-positive-trend-slope --max-close-vs-trend 0.25 --filter-max-ret-20 0.25
```

扫描全市场潜伏池：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern accumulation_setup --top 120 --min-score 50 --stages accumulation --base-window 250 --max-base-range 0.45 --min-amount-ma20 100000000 --min-volume-ratio 1.05 --max-volume-ratio 2.20 --require-positive-trend-slope --max-close-vs-trend 0.12 --max-close-vs-cost 0.18 --filter-max-ret-20 0.15 --max-ret-60 0.30 --max-price-position 0.82
```

潜伏池评分采用多周期口径：

- 月线位置 25%：看 36 个月区间位置、月线波动区间和 12 月均线斜率。
- 周线蓄势 30%：看 20 周区间位置、周线波动压缩、20 周均线斜率和周线量能。
- 日线触发 45%：看 250 日平台位置、长期成本偏离、日线温和放量和近 20/60 日涨幅。
- `setup_phase` 会标注为长期低位蓄势、周线右侧启动、日线触发观察、低位潜伏观察、接近突破确认或已过热。

给形态候选池做情绪评分：

```powershell
python -m quant_a_stock.cli sentiment-score --latest-scan --target-date 2026-06-12 --top 50 --display-top 30 --news-days 7
```

生成市场主线：

```powershell
python -m quant_a_stock.cli market-theme --target-date 2026-06-12 --top 20
```

合成最终研究候选池：

```powershell
python -m quant_a_stock.cli research-candidates --target-date 2026-06-12 --top 30
```

归档当天快照：

```powershell
python -m quant_a_stock.cli snapshot-research --target-date 2026-06-12
```

生成每日中文复盘报告：

```powershell
python -m quant_a_stock.cli daily-research-summary --target-date 2026-06-12 --top 30
```

## 每天主要看哪些报告

优先看：

- `daily_research_summary_*.md`：每日主报告，综合市场温度、主线、候选分层、持续性和风险提醒。
- `research_candidates_*.md`：最终候选池，主要看 A/B 级。
- `market_theme_*.md`：当天市场主线。
- `sentiment_watchlist_*.md`：候选股情绪细节。

辅助看：

- `scan_accumulation_setup_*.csv`：潜伏池形态候选。
- `scan_base_breakout_setup_*.csv`：纯形态候选。
- `research_candidates_*.csv`：需要排序、筛选、做表格时看。

不需要每天看：

- `research_backtest_*.csv`
- `research_backtest_candidates_*.csv`
- `research_backtest_holdings_*.csv`
- `research_optimize_*.csv`
- `backtest_*.csv`
- `compare_*.csv`
- `validate_*.csv`

这些是策略研究和参数验证报告，不是每日选股报告。

## 复盘优先级

优先人工复盘：

- `research_tier = A`
- `research_score` 靠前
- `stage = accumulation`
- `setup_phase` 属于长期低位蓄势、周线右侧启动或日线触发观察
- `matched_theme` 命中当天强主线
- `total_penalty` 低
- `risk_notice_titles` 为空或只是常规披露

谨慎观察：

- 情绪分很高但近 20 日涨幅过热。
- 形态分很高但情绪分很低。
- 主线未命中，只有个股独立异动。
- `stage = pre_breakout` 或 `near_breakout`，位置已经接近高点，只能按突破确认观察，不当低位潜伏。
- 月线位置过高、周线已经明显扩散、日线近 20/60 日涨幅过热。
- 公告风险命中问询、处罚、立案、诉讼、减持、质押、担保逾期等关键词。

## 消息面平衡口径

现在情绪面不再只看新闻数量，而是分成几类证据：

- 核心新闻：标题里直接出现股票代码或公司简称，权重最高。
- 泛消息：行业资金流、融资余额、若干股名单等泛新闻，只给少量辅助分。
- 研报覆盖：近 90 天研报数量、买入/增持类评级，用来判断机构关注度。
- 热门关键词：用于识别概念标签，但不单独决定结论。
- 涨停/强势池：用于判断短线资金是否已经关注。
- 公告风险：问询、处罚、立案、诉讼、减持、质押、担保逾期等命中时扣分。
- 技术位置：最终仍要看形态、涨幅透支、量能和主线匹配。

复盘时优先找这类票：

- 形态分高，且不是单日过热。
- 核心新闻或研报有真实催化。
- 热门关键词能贴上当天强主线。
- 泛消息多但核心新闻少的票，不轻易当作强情绪票。
- 主线强但个股消息弱的票，先放观察池。
- 个股消息强但不在主线里，降低仓位假设，只做个股事件观察。

## 报告清理规则

`reports/` 是临时输出目录，可以定期清理。

建议保留：

- 最新一组 `scan_accumulation_setup_*.csv`
- 最新一组 `scan_base_breakout_setup_*.csv`
- 最新一组 `sentiment_watchlist_*.md/.csv`
- 最新一组 `market_theme_*.md/.csv`
- 最新一组 `research_candidates_*.md/.csv`
- 最新一组 `daily_research_summary_*.md`
- 最新一组 `daily_research_candidates_*.csv`
- 最新一组 `research_backtest_*.csv`
- 最新一组 `research_optimize_*.csv`

可以删除：

- 早期测试用的 `backtest_*.csv`
- 早期测试用的 `compare_*.csv`
- 早期测试用的 `validate_*.csv`
- 旧的 `scan_base_breakout_setup_*.csv`
- 旧的 `sentiment_watchlist_*.md/.csv`
- 旧的 `market_theme_*.md/.csv`
- 旧的 `research_backtest_candidates_*.csv`

真正要长期保存的是：

- `data/snapshots/research/YYYY-MM-DD/`

这个目录保存每天的研究快照，后续做历史情绪和市场主线回测时会用到。
