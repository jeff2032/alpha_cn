# 数据闭环与保留策略

这个项目的数据分成四层：源数据、数仓主数据、运行产物、人工知识库。原则是：**机器可复盘的数据进数仓，人看的结论进 Obsidian，中间产物只保留近期排障窗口。**

## 数据分层

| 层 | 路径 | 定位 | 保留策略 |
| --- | --- | --- | --- |
| 原始 CSV 缓存 | `data/cache/akshare/daily/` | AKShare 下载后的日线缓存，当前增量补数依赖它 | 暂不清理 |
| Parquet 数仓 | `data/warehouse/parquet/` | 结构化主数据，行情、候选、情绪、主题、复盘都应进这里 | 长期保留 |
| DuckDB 查询壳 | `data/warehouse/alpha_cn.duckdb` | 通过 view 查询 Parquet，不是主数据副本 | 保留，可重建 |
| 每日研究快照 | `data/snapshots/research/` | 入仓前/排障用的日期快照 | 入仓后保留最近 30 天 |
| 机器报告 | `reports/` | CSV/Markdown 运行产物 | 入仓/同步后保留最近 14 天 |
| 运维报告 | `reports/ops/` | 夜间任务状态和失败原因 | 保留最近 60 天 |
| 日志 | `logs/` | 排障用运行日志 | 保留最近 30 天 |
| Obsidian | `G:\Program Files (x86)\Obsidian_base\中国A股荐股\` | 人看的复盘、计划和策略沉淀 | 人工保留，不自动清理 |

## 当前闭环

每日夜间准备完成后，应至少具备：

1. 日线 CSV 已补到目标交易日。
2. 候选、情绪、主题、复盘报告已生成。
3. `snapshot-research` 已归档当天快照。
4. `warehouse-sync-universe` 已写入股票池维表。
5. `warehouse-sync-candles` 已同步日线 Parquet。
6. `warehouse-backfill-snapshots` 已把研究快照写入仓库。
7. `track-candidates` 已把 A2/A3/B2 候选生命周期写入仓库。
8. `warehouse-ingest` 已索引最新报告和研究结果。
9. Obsidian 中有 `每日复盘/数据截至日/` 和必要时的 `开盘计划/计划日期.md`。

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
- 开盘计划和人工判断进入 Obsidian；后续如果要量化“人工是否采纳”，再单独入仓。

## 复盘样本标签

`research_review_details` 会给候选样本补充统一标签：

| 字段 | 含义 |
| --- | --- |
| `sample_type` | 样本类型，当前候选为 `candidate`，错过样本为 `miss` |
| `model_bucket` | 模型桶：`A1/A2_early_setup`、`A3_trend_follow`、`B_watchlist`、`miss_learnable`、`miss_event_only` |
| `action_bucket` | 动作分组：主攻-A2启动确认、主攻-A3趋势延续、补票-B2a主线扩散、观察-B2b主题待确认、观察或回避 |
| `evaluation_horizon` | 评价窗口：潜伏/启动看 `3d_5d`，趋势看 `1d_3d`，观察池看 `observe_1d_3d` |
| `preferred_horizon` | 当前样本优先评价周期 |
| `preferred_ret` | 当前样本优先评价周期收益 |
| `outcome_label` | `hit`、`loss`、`neutral`、`intraday_fade`、`volatile_win` |
| `risk_level` | 低 / 中 / 中高 / 高 |
| `risk_tags` | 样本风险标签 |
| `is_learnable` | 是否适合进入规则反推 |

复盘报告会新增：

- 模型桶 1/3/5 日表现
- 模型桶首日表现
- 动作分组 1/3/5 日表现
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
- `补票-B2a主线扩散`
- `补票-B2强主题`，历史兼容桶名
- `观察-B2b主题待确认`

如果同一只股票消失不超过 3 个交易日后重新入池，仍算同一轮机会；超过 3 个交易日后回来，建立新的生命周期。A1 低位潜伏先只做观察，不进入主生命周期，除非后续升级到 B2/A2/A3。

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
