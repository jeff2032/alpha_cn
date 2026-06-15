# Windows 自动运行每日选股任务

当前推荐时间：每天 16:30。

原因：

- A 股 15:00 收盘后，日线数据和新闻/研报数据通常需要一点时间同步。
- 16:30 比 15:10 更稳，能减少因为数据源未更新导致的空跑。
- 任务会先用 `000001` 做探针；如果数据源还没更新到当天，就跳过全市场更新。

## 自动任务执行内容

任务计划程序会调用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "G:\OwnProject\alpha_cn\scripts\run_daily_research.ps1"
```

脚本顺序：

1. 周末自动跳过。
2. 用 `000001` 检查当天日线是否已可用。
3. 补充过期股票缓存。
4. 扫描突破确认池。
5. 扫描低位潜伏池。
6. 生成情绪面报告。
7. 生成市场主线报告。
8. 合成最终研究候选池。
9. 归档到 `data/snapshots/research/YYYY-MM-DD/`。
10. 生成每日中文复盘报告 `daily_research_summary_*.md`。

## 每天看什么

优先看：

- `reports/daily_research_summary_*.md`
- `reports/research_candidates_*.md`
- `reports/market_theme_*.md`
- `reports/sentiment_watchlist_*.md`

日志位置：

- `logs/daily_research/`

## 手动跑一次

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1
```

如果想周末或节假日强制跑一次：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1 -Force
```
