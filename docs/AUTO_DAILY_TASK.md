# Windows 自动运行每日数据任务

当前推荐时间：

- 每天 16:30 自动连续跑夜间准备：先刷新股票池并补股票日线和 ETF/指数温度池，再跑形态扫描、情绪、市场主线、公司资料、公告风险、快照、日报、滚动复盘、行情仓库同步、研究结果入库和中间层事实表派生。
- 每天早上 7 点左右手动和 Codex 一起跑快决策、荐股结果与策略反思。

原因：

- A 股 15:00 收盘后，日线数据和新闻/研报数据通常需要一点时间同步。
- 16:30 比 15:10 更稳，能减少因为数据源未更新导致的空跑。
- 16:30 自动任务做完整夜间准备，所有漫长的数据准备都放在这里连续跑。
- 如果行情补数后仍有大量标的没到目标交易日，脚本会在同一个 16:30 任务内等待并重试，默认最多 6 轮、每轮间隔 30 分钟。
- 多轮重试后仍未达标时，脚本才会跳过后续慢分析，直接写运维报告，避免用不完整行情生成结论。
- 日常补数会先合并旧股票池、多个在线股票池和 `config/required_symbols.csv` 必保清单；只要数据源能下载，就不能因为股票池旧、代码漏或单次接口失败而长期漏数。
- 行情补数使用增量模式，只刷新过期标的最近一段数据，不会每天从 2020 年全量重拉。
- 默认用 `sina` 数据源补数；由于 `sina` 在高并发下可能触发 AKShare 依赖崩溃，脚本会自动把 Sina 的有效并发保护到 2。
- 目标日期按 A 股真实交易日处理，不只看工作日；节假日会自动回退到本地最近一个已缓存交易日。
- 早上手动跑荐股时，默认数据目标日取上一个交易日；Obsidian 只写用户结论层：`开盘决策/计划日期.md`、`持仓观察/计划日期.md` 和 `复盘摘要/数据截至日.md`。

## 16:30 夜间连续准备任务

任务计划程序会调用：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "G:\OwnProject\alpha_cn\scripts\run_nightly_research_prep.ps1"
```

脚本顺序：

1. 周末自动跳过。
2. 刷新股票池：合并旧池、在线数据源和 `config/required_symbols.csv`。
3. 增量补充过期股票缓存，默认 `Workers=6`，回看 60 个自然日。
4. 复查缓存是否到目标交易日，生成 `data/universe/stale_after_nightly.csv`。
5. 如果过期标的数超过阈值，默认 30 只，等待 30 分钟后重试补数。
6. 默认最多重试 6 轮；仍未达标时，跳过后续慢分析，只输出运维报告。
7. 补 ETF/指数温度池：`510300`、`510500`、`159915`；主源失败或日期滞后时自动尝试备用源。
8. 扫描突破确认池。
9. 扫描低位潜伏池。
10. 扫描强趋势回踩/再启动池。
11. 生成情绪面缓存，默认扩到前 180 个候选。
12. 生成市场主线。
13. 资金流先对核心 30 只候选做快速探测；未达到最低成功率时明确降级并继续，不让可选数据源阻断公告风险、候选池和数仓闭环。
14. 生成巨潮结构化公告风险事件缓存。
15. 合成最终研究候选池，并抓公司资料、公告风险等慢数据；如果同日资金流、巨潮风险和问财导入报告存在，会自动合并。
16. 归档到 `data/snapshots/research/YYYY-MM-DD/`。
17. 生成每日中文复盘报告。
18. 生成近两周候选池滚动复盘报告。
19. 生成 A1/A2/A3/B2 候选生命周期跟踪并写入仓库。
20. 写入股票池维表。
21. 把本地股票和 ETF/指数日线 CSV 缓存增量同步到 Parquet。
22. 回填当天研究快照。
23. 写入最新研究报告和复盘结果，同时生成 `run_manifest` 和 `data_quality_daily`。
24. 输出夜间准备报告。

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
9. 生成 Obsidian 用户决策层：`开盘决策\计划日期.md`、`持仓观察\计划日期.md` 和 `复盘摘要\数据截至日.md`。完整候选、情绪、滚动复盘和生命周期明细只保留在项目内部 `reports/` 与数仓。

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
- `开盘决策/YYYY-MM-DD.md`：按计划交易日归档，是早上优先看的决策页。
- `持仓观察/YYYY-MM-DD.md`：按计划交易日归档，只处理已有持仓。
- `复盘摘要/YYYY-MM-DD.md`：按数据截至日归档，只放一页短复盘。
- 同一个数据日重复运行会覆盖 `复盘摘要`；同一个计划日重复运行会覆盖 `开盘决策` 和 `持仓观察`。
- 开盘决策要以计划交易日命名，方便用户决策；推荐和观察可以用计划日做主语，但市场温度、市场主线、滚动复盘、生命周期状态这类历史事实要用数据日做主语。例如 `2026-07-02.md` 里的市场主题应写成 `2026-07-01 收盘主线回顾`，市场判断应写成 `2026-07-01 收盘市场口径`，避免把上一交易日事实误读为计划日预测。

持仓观察读取本地文件：

```text
data/manual/holdings.csv
```

字段参考 `config/holdings.example.csv`。`data/` 不提交 git，真实持仓只保存在本机。

## 手动跑荐股

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1
```

如果想明确指定“数据截至日”和“计划日期”，例如 2026-06-18 开盘前基于 2026-06-17 数据做计划：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1 -TargetDate 2026-06-17 -PlanDate 2026-06-18
```

日期关系必须保持清楚：

- `TargetDate` 是数据截至日，只能填已经收盘且已准备好的交易日。
- `PlanDate` 是要看的开盘计划日期，正常应是 `TargetDate` 的下一个交易日。
- 例如 `2026-07-07` 开盘计划应使用 `-TargetDate 2026-07-06 -PlanDate 2026-07-07`，不能使用 `2026-07-07` 当天数据。
- 如果不传 `-PlanDate`，脚本会默认取 `TargetDate` 后的下一个交易日；历史补跑时会优先从本地缓存推断真实下一交易日。

如果只想生成项目内报告，不想同步到 Obsidian：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1 -NoObsidianExport
```

如果项目内报告已经生成，只想把某个数据日补同步到 Obsidian，并生成对应用户决策文档：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1 -TargetDate 2026-07-03 -PlanDate 2026-07-06 -ExportOnly
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
