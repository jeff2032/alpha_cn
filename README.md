# quant_a_stock

这是一个 A 股日线 long-only 量化研究与回测项目。

第一阶段的目标不是实盘，而是把研究闭环做稳：

- 用 AKShare 下载 A 股 / ETF 日线数据
- 清洗并缓存 CSV 数据
- 运行策略信号
- 按 A 股交易成本做回测
- 做参数扫描
- 按年份和标的验证
- 输出 CSV 报告
- 扫描“长期平台后早期突破”形态候选
- 给候选股生成情绪面辅助评分和市场主线观察报告

第一阶段不做实盘、不做分钟线、不做做空、不做高频、不做 AI，也不直接给买卖建议。情绪面只作为研究辅助，不能替代交易计划和风险控制。

## 安装

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

AKShare 只在真实下载数据时需要。测试使用合成数据。

## 数据下载

下载并缓存 ETF 日线数据：

```powershell
python -m quant_a_stock.cli sync-daily --symbols 510300 159915 510500 --since 2020-01-01 --adjust qfq
```

如果 AKShare 的东方财富接口临时不可用，可以显式使用 Sina ETF 备用源。这个源适合先跑通研究流程，但不支持 qfq/hfq 复权控制：

```powershell
python -m quant_a_stock.cli sync-daily --symbols 510300 159915 510500 --since 2020-01-01 --asset-type etf --etf-provider sina --adjust none
```

下载小股票池。Sina 个股接口支持 `qfq`，但不要无节制高频抓取：

```powershell
python -m quant_a_stock.cli sync-daily --symbols 688146 600519 300750 --since 2020-01-01 --asset-type stock --stock-provider sina --adjust qfq
```

如果上游股票列表接口可用，可以生成 A 股股票池：

```powershell
python -m quant_a_stock.cli list-stock-universe --provider auto --markets sh sz --output data/universe/a_stock.csv
```

批量下载股票池，支持断点续跑和限速：

```powershell
python -m quant_a_stock.cli sync-stock-universe --universe-file data/universe/a_stock.csv --since 2020-01-01 --stock-provider sina --adjust qfq --sleep 1.5 --skip-existing
```

小批量烟测：

```powershell
python -m quant_a_stock.cli sync-stock-universe --symbols 688143 688146 600519 --since 2020-01-01 --stock-provider sina --adjust qfq --limit 3
```

## 数据运维

检查股票池里还有多少没有缓存：

```powershell
python -m quant_a_stock.cli cache-status --universe-file data/universe/a_stock.csv --show-missing --top 20 --output-missing data/universe/missing.csv
```

检查本地缓存是否更新到目标日期：

```powershell
python -m quant_a_stock.cli cache-date-status --universe-file data/universe/a_stock.csv --show-stale --top 30 --output-stale data/universe/stale.csv
```

常用数据运维流程见 [docs/DATA_OPS.md](G:/OwnProject/alpha_cn/docs/DATA_OPS.md)。

## 回测

从缓存数据运行回测：

```powershell
python -m quant_a_stock.cli backtest --from-cache --strategy sma_trend_filter --symbols 510300 159915 --timeframe 1d
```

当前研究策略：

- `sma_trend_filter`：SMA 趋势过滤基线策略
- `base_breakout_setup`：明显加速前的早期平台突破形态
- `donchian_breakout`：前高突破并带长期趋势过滤
- `rsi_reversion`：长期趋势内的 RSI 超跌反弹
- `ema_pullback_trend`：EMA 多头趋势内的 RSI 回调

比较多个策略的组合表现：

```powershell
python -m quant_a_stock.cli compare --symbols 510300 159915 510500
```

运行某个策略：

```powershell
python -m quant_a_stock.cli backtest --from-cache --strategy rsi_reversion --symbols 510300 159915 510500 --rsi-entry 35 --rsi-exit 55 --trend-window 120
```

扫描 SMA 参数：

```powershell
python -m quant_a_stock.cli optimize --strategy sma_trend_filter --symbols 510300 159915 --fast-windows 10,20,30 --slow-windows 50,100 --trend-windows 120,200
```

按年份验证：

```powershell
python -m quant_a_stock.cli validate --strategy sma_trend_filter --symbols 510300 159915 --since 2020-01-01
```

## 形态扫描

扫描缓存标的里的早期平台突破形态：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern base_breakout_setup --symbols 510300 159915 510500 --top 20
```

扫描全市场早期候选：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern base_breakout_setup --top 50 --min-score 50 --stages watch near_breakout --min-amount-ma20 100000000 --require-positive-trend-slope --max-close-vs-trend 0.25 --filter-max-ret-20 0.25
```

扫描全市场低位潜伏候选：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern accumulation_setup --top 120 --min-score 50 --stages accumulation --base-window 250 --max-base-range 0.45 --min-amount-ma20 100000000 --min-volume-ratio 1.05 --max-volume-ratio 2.20 --require-positive-trend-slope --max-close-vs-trend 0.12 --max-close-vs-cost 0.18 --filter-max-ret-20 0.15 --max-ret-60 0.30 --max-price-position 0.82
```

`accumulation_setup` 会把月线位置、周线蓄势和日线触发合成多周期分，并输出 `setup_phase` 节奏标签。

把早期形态当成策略回测：

```powershell
python -m quant_a_stock.cli backtest --from-cache --strategy base_breakout_setup --symbols 510300 159915 510500
```

## 情绪面辅助

对最新一份形态扫描报告里的候选股做情绪评分：

```powershell
python -m quant_a_stock.cli sentiment-score --latest-scan --target-date 2026-06-12 --top 20 --display-top 20 --news-days 7
```

也可以直接传入自选股：

```powershell
python -m quant_a_stock.cli sentiment-score --symbols 600160 601137 300568 --target-date 2026-06-12 --news-days 7
```

生成市场主线观察报告：

```powershell
python -m quant_a_stock.cli market-theme --target-date 2026-06-12 --top 20
```

当前情绪评分主要参考东财人气排名、个股新闻、热门关键词、涨停池和强势股池。它适合用于“形态候选池”的二次过滤：优先看形态分高、情绪分不弱、同时落在市场主线里的标的。

合成最终研究候选池：

```powershell
python -m quant_a_stock.cli research-candidates --target-date 2026-06-12 --top 30
```

这个命令会合并最新形态报告、最新情绪报告和最新市场主线报告，并补充上市天数、量能过热扣分、涨幅过热扣分、风险公告扣分、主线命中加分和行业同涨确认。

回测研究候选池的技术代理版本：

```powershell
python -m quant_a_stock.cli research-backtest --years 2 --top-n 10 --rebalance-frequency W --min-score 50 --min-amount-ma20 100000000 --max-close-vs-trend 0.25 --filter-max-ret-20 0.25
```

这个回测只使用历史日线形态和量价指标，不使用当前情绪接口倒推过去，避免未来函数。

扫描研究候选池参数：

```powershell
python -m quant_a_stock.cli research-optimize --years 2 --top-ns 5,10,20 --min-scores 45,50,55 --max-ret-20s 0.15,0.20,0.25 --rebalance-frequencies W M --min-amount-ma20 100000000 --max-close-vs-trend 0.25
```

当前两年技术代理回测里较稳的一组参数：

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

日常选股流程见 [docs/DAILY_RESEARCH.md](G:/OwnProject/alpha_cn/docs/DAILY_RESEARCH.md)。主要看 `daily_research_summary_*.md`，它会把市场温度、主线、候选分层、持续性和风险提醒合到一份中文报告里。

## 项目结构

```text
quant_a_stock/
  config/settings.example.yaml
  data/cache/
  data/universe/
  docs/
  reports/
  src/quant_a_stock/
  tests/
```

`data/cache/` 和 `reports/` 不提交 git。
