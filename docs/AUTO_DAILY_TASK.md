# Windows 自动运行每日数据任务

当前推荐时间：

- 每天 16:30 自动连续跑夜间准备：先补股票日线和 ETF/指数温度池，再跑形态扫描、情绪、市场主线、公司资料、公告风险、快照、日报、滚动复盘、行情仓库同步和研究结果入库。
- 每天早上 7 点左右手动和 Codex 一起跑快决策、荐股结果与策略反思。

原因：

- A 股 15:00 收盘后，日线数据和新闻/研报数据通常需要一点时间同步。
- 16:30 比 15:10 更稳，能减少因为数据源未更新导致的空跑。
- 16:30 自动任务做完整夜间准备，所有漫长的数据准备都放在这里连续跑。
- 如果行情补数后仍有大量标的没到目标交易日，脚本会在同一个 16:30 任务内等待并重试，默认最多 6 轮、每轮间隔 30 分钟。
- 多轮重试后仍未达标时，脚本才会跳过后续慢分析，直接写运维报告，避免用不完整行情生成结论。
- 日常补数使用增量模式，只刷新过期标的最近一段数据，不会每天从 2020 年全量重拉。
- 默认用 `sina` 数据源补数；由于 `sina` 在高并发下可能触发 AKShare 依赖崩溃，脚本会自动把 Sina 的有效并发保护到 2。
- 目标日期按 A 股真实交易日处理，不只看工作日；节假日会自动回退到本地最近一个已缓存交易日。
- 早上手动跑荐股时，默认数据目标日取上一个交易日；Obsidian 会把完整复盘写入 `每日复盘/数据截至日/`，把开盘前一页纸写入 `开盘计划/计划日期.md`。

## 16:30 夜间连续准备任务

任务计划程序会调用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "G:\OwnProject\alpha_cn\scripts\run_nightly_research_prep.ps1"
```

脚本顺序：

1. 周末自动跳过。
2. 增量补充过期股票缓存，默认 `Workers=6`，回看 60 个自然日。
3. 复查缓存是否到目标交易日，生成 `data/universe/stale_after_nightly.csv`。
4. 如果过期标的数超过阈值，默认 30 只，等待 30 分钟后重试补数。
5. 默认最多重试 6 轮；仍未达标时，跳过后续慢分析，只输出运维报告。
6. 补 ETF/指数温度池：`510300`、`510500`、`159915`；主源失败或日期滞后时自动尝试备用源。
7. 扫描突破确认池。
8. 扫描低位潜伏池。
9. 扫描强趋势回踩/再启动池。
10. 生成情绪面缓存，默认扩到前 180 个候选。
11. 生成市场主线。
12. 合成最终研究候选池，并抓公司资料、公告风险等慢数据。
13. 归档到 `data/snapshots/research/YYYY-MM-DD/`。
14. 生成每日中文复盘报告。
15. 生成近两周候选池滚动复盘报告。
16. 生成 A2/A3/B2 候选生命周期跟踪并写入仓库。
17. 写入股票池维表。
18. 把本地股票和 ETF/指数日线 CSV 缓存增量同步到 Parquet。
19. 回填当天研究快照。
20. 写入最新研究报告和复盘结果。
21. 输出夜间准备报告。

日志和状态报告：

- 行情补数日志：`logs/data_sync/`
- 日志：`logs/nightly_prep/`
- 状态报告：`reports/ops/nightly_prep_*.md`

如果早上发现报告里有失败步骤，可以先看最新的 `reports/ops/nightly_prep_*.md`，再决定是否手动补跑。

Windows 下建议用统一入口查看状态：

```powershell
.\scripts\alpha.ps1 task-status
.\scripts\alpha.ps1 latest-ops
```

## 7 点手动荐股

早上打开 Codex 后说“跑荐股和复盘”，执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1
```

脚本顺序：

1. 检查目标数据日是否已经准备好。
2. 必要时补少量过期行情。
3. 扫描三类形态池。
4. 生成情绪面报告。
5. 生成市场主线报告。
6. 快速合成最终研究候选池，默认跳过公司资料和公告风险联网请求。
7. 归档到 `data/snapshots/research/YYYY-MM-DD/`。
8. 生成每日中文复盘报告 `daily_research_summary_*.md`。
9. 复制 Markdown 报告到 Obsidian：完整复盘进入 `中国A股荐股\每日复盘\数据截至日\`，开盘前计划进入 `中国A股荐股\开盘计划\计划日期.md`。

早上脚本的重点是快，不把慢接口放进决策链路；夜间准备成功时，早上主要是刷新和确认。

项目内优先看：

- `reports/daily_research_summary_*.md`
- `reports/research_candidates_*.md`
- `reports/market_theme_*.md`
- `reports/sentiment_watchlist_*.md`

日志位置：

- `logs/daily_research/`

Obsidian 同步位置：

- `G:\Program Files (x86)\Obsidian_base\中国A股荐股\`
- `每日复盘/YYYY-MM-DD/`：按数据截至日归档，包含 `每日推荐复盘.md`、`最终候选池.md`、`市场主线.md`、`情绪观察.md`、`滚动复盘.md`、`策略反思.md`。
- `开盘计划/YYYY-MM-DD.md`：按计划交易日归档，是早上优先看的开盘前一页纸。
- `策略迭代/`：长期沉淀规则复盘、miss 样本反推和风险过滤。
- 同一个数据日重复运行会覆盖自动生成的复盘报告；同一个计划日重复运行会覆盖开盘计划文件，但不会覆盖每日复盘里的 `策略反思.md`。

## 手动跑荐股

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1
```

如果想明确指定“数据截至日”和“计划日期”，例如 2026-06-18 开盘前基于 2026-06-17 数据做计划：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1 -TargetDate 2026-06-17 -PlanDate 2026-06-18
```

如果只想生成项目内报告，不想同步到 Obsidian：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1 -NoObsidianExport
```

如果数据源不稳定、失败数变多，可以临时降低并行数：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1 -Workers 4
```

如果想周末或节假日强制跑一次：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1 -Force
```

如果周末或月末需要更稳地刷新 250 日平台指标和最近复权，可以临时拉长回看窗口：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1 -Force -LookbackDays 450
```

如果需要更严格地重算月线三年结构，可以用深刷新：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1 -Force -LookbackDays 1200
```
