# 数据闭环与保留策略

这个项目的数据分成三层：用户结论层、中间复盘层、原始数据层。原则是：**用户看 Obsidian 的短结论，我们看 DuckDB + Parquet 的结构化中间层，原始行情/公告/主题只作为可追溯底座。**

## 数据分层

| 层 | 路径 | 定位 | 保留策略 |
| --- | --- | --- | --- |
| 用户结论层 | `G:\Program Files (x86)\Obsidian_base\中国A股荐股\` | 给持仓人/使用者看的短结论：开盘决策、持仓观察、复盘摘要 | 人工保留，不自动清理 |
| 中间复盘层 | `data/warehouse/parquet/` + `data/warehouse/alpha_cn.duckdb` | 给我们复盘、聚合、反推和因子挖掘用，稳定保存候选、生命周期、miss、因子诊断和策略复盘事实表 | 长期保留；DuckDB 可重建，Parquet 是主存储 |
| 原始数据层 | `data/cache/`、`data/snapshots/research/`、`reports/`、`logs/` | 行情、行业、公告、主题、候选快照、运行报告和日志；用于排障、回填和可追溯 | 行情缓存暂不清理；快照、reports 和 logs 按保留策略清理 |

## 当前闭环

每日夜间准备完成后，应至少具备：

1. 日线 CSV 已补到目标交易日。
2. 候选、情绪、主题、复盘报告已生成。
3. `snapshot-research` 已归档当天快照。
4. `warehouse-sync-universe` 已写入股票池维表。
5. `warehouse-sync-candles` 已同步日线 Parquet。
6. `warehouse-backfill-snapshots` 已把研究快照写入仓库，并派生 `research_candidate_daily`、`stock_market_attitude_daily`。
7. `track-candidates` 已把 A1/A2/A3/B2 候选生命周期写入仓库。
8. `warehouse-ingest` 已索引最新报告和研究结果，并派生 miss、因子诊断、策略复盘中间层。
9. Obsidian 中有 `复盘摘要/数据截至日.md`、`开盘决策/计划日期.md` 和 `持仓观察/计划日期.md`。

## 日常检查

统一使用：

```powershell
.\scripts\alpha.ps1 data-loop -TargetDate 2026-06-22 -PlanDate 2026-06-23
```

看仓库表：

```powershell
.\scripts\alpha.ps1 warehouse-status
```

看清理预案：

```powershell
.\scripts\alpha.ps1 retention-plan
```

`retention-plan` 是 dry-run，只列出候选项，不会删除文件。

## 下一步原则

- 因子挖掘优先读 `data/warehouse/parquet/` 或 DuckDB view。
- 不再从散落的 `reports/*.csv` 拼长期统计。
- `reports/` 只作为当天运行产物和排障入口。
- `data/snapshots/` 只作为快照过渡层，不作为最终主存储。
- 开盘决策、持仓观察和复盘摘要进入 Obsidian；后续如果要量化“人工是否采纳”，再单独入仓。

## 中间层事实表

中间层不追求好看，追求能查、能聚合、能反推。当前稳定表：

| 表 | 粒度 | 用途 |
| --- | --- | --- |
| `research_candidate_daily` | 每天每只最终候选一行 | 保存分层、分组、分数、主题、风险、预期观察周期、原因标签和市场态度摘要 |
| `stock_market_attitude_daily` | 每天每只候选一行 | 保存热度、资金承接、主题共振、盘面态度、事件、风险和拥挤度，输出强确认/温和确认/冷启动/虚热/过热分歧/风险压制 |
| `candidate_lifecycle_daily` | 每个生命周期每天一行 | 观察新入池、继续、升级、降级、消失、命中、失败、移出 |
| `missed_opportunity_daily` | 每个明显错过样本一行 | 记录当天大涨但没进入候选的票，以及 miss 原因、风险和是否可学习 |
| `factor_diagnostics_daily` | 每个复盘聚合项一行 | 保存分层、动作桶、模型桶、阶段、亏损归因、miss 可学习性的统计结果 |
| `strategy_review_daily` | 每个策略片段一行 | 把复盘统计粗标为有效、中性、拖后腿或样本不足，供后续策略反思使用 |

这些表由 `warehouse-backfill-snapshots` 和 `warehouse-ingest` 自动派生，不需要新增日常命令。

## 复盘样本标签

`research_review_details` 会给候选样本补充统一标签：

| 字段 | 含义 |
| --- | --- |
| `sample_type` | 样本类型，当前候选为 `candidate`，错过样本为 `miss` |
| `model_bucket` | 模型桶：`A1/A2_early_setup`、`A3_trend_follow`、`B2a_theme_spread`、`B_surge_replenish`、`B2b_theme_watch`、`B_watchlist`、`miss_learnable`、`miss_event_only` |
| `action_bucket` | 动作分组：主攻-A2启动确认、主攻-A3趋势延续、观察-B2a主线扩散待升级、观察-B2s主线突发待确认、观察-B2b主题待确认、观察或回避 |
| `evaluation_horizon` | 评价窗口：A1 看 10/20/30 日，A2 看 3/5/10/15 日，A3 看 1/3/5/10 日，观察池先看是否升级 |
| `preferred_horizon` | 当前样本优先评价周期 |
| `preferred_ret` | 当前样本优先评价周期收益 |
| `outcome_label` | `hit`、`loss`、`neutral`、`intraday_fade`、`volatile_win` |
| `risk_level` | 低 / 中 / 中高 / 高 |
| `risk_tags` | 样本风险标签 |
| `is_learnable` | 是否适合进入规则反推 |

复盘报告会新增：

- 模型桶 1/3/5/10/15/20/30 日表现
- 模型桶首日表现
- 动作分组 1/3/5/10/15/20/30 日表现
- 动作分组首日表现
- 亏损样本归因
- Miss 样本可学习性

后续做因子挖掘时，优先以 `action_bucket + model_bucket + evaluation_horizon + is_learnable` 作为样本过滤口径。

## 候选生命周期

候选快照回答“当天模型选了什么”，生命周期表回答“选进去之后怎么走”。长期保存两张事实表：

| 表 | 粒度 | 用途 |
| --- | --- | --- |
| `candidate_lifecycles` | 每只股票每一轮入池机会一行 | 看首次入池、最高分组、当前状态、命中/失败标签、观察窗口收益 |
| `candidate_lifecycle_daily` | 每个生命周期在每个快照日一行 | 看新入池、升级、降级、消失、继续跟踪和入池以来收益 |

当前主生命周期只覆盖：

- `主攻-A2启动确认`
- `主攻-A3趋势延续`
- `观察-B2a主线扩散待升级`
- `观察-B2s主线突发待确认`
- `补票-B2a主线扩散`，历史兼容桶名
- `补票-主线突发`，历史兼容桶名
- `补票-B2强主题`，历史兼容桶名
- `观察-B2b主题待确认`

如果同一只股票消失不超过 3 个交易日后重新入池，仍算同一轮机会；超过 3 个交易日后回来，建立新的生命周期。A1 低位潜伏也进入生命周期，但观察窗口更长，重点看后续是否补量、补主题、升级到 B2/A2/A3，不能和 A3 趋势票用同一个短周期标准评价。

手动生成：

```powershell
python -m quant_a_stock.cli track-candidates --since 2026-06-12 --until 2026-06-24 --top 50
```

生成结果：

- `reports/candidate_lifecycles_*.csv`
- `reports/candidate_lifecycle_daily_*.csv`
- `reports/candidate_lifecycle_tracking_*.md`
- `data/warehouse/parquet/candidate_lifecycles/`
- `data/warehouse/parquet/candidate_lifecycle_daily/`
