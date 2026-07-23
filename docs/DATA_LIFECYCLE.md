# 数据闭环与保留策略

这个项目的数据分成四层：用户结论层、机器上下文层、中间复盘层、原始数据层。原则是：**用户看 Obsidian 的短结论，AI/外部入口读 Context Pack，我们看 DuckDB + Parquet 的结构化中间层，原始行情/公告/主题只作为可追溯底座。**

## 数据分层

| 层 | 路径 | 定位 | 保留策略 |
| --- | --- | --- | --- |
| 用户结论层 | `G:\Program Files (x86)\Obsidian_base\中国A股荐股\` | 给持仓人/使用者看的短结论：开盘决策、持仓观察、复盘摘要 | 人工保留，不自动清理 |
| 机器上下文层 | `data/context/research/`、`data/context/fundamental/` | 给 AI 解读、Web 壳或其他项目读取的结构化 JSON：市场、主线、候选、决策信号、基本面深研交接清单、复盘、生命周期、持仓匹配 | 可由快照重复生成 |
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
8. `decision-signals` 已把候选池派生成结构化处理口径。
9. `fundamental-watchlist` 已导出给 `ai-berkshire` 的基本面深研交接清单。
10. `warehouse-ingest` 已索引最新报告和研究结果，并派生决策信号、基本面交接、miss、因子诊断、策略复盘中间层。
11. `export-context-pack` 已生成 `data/context/research/数据截至日/plan_计划日期.json`。
12. Obsidian 中有 `复盘摘要/数据截至日.md`、`开盘决策/计划日期.md` 和 `持仓观察/计划日期.md`。

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
- `data/snapshots/research/<交易日>/` 是不可变研究事实快照，长期保留，用于审计和历史回填；DuckDB + Parquet 仍是统计查询主存储。
- 历史规则重建写入 `data/snapshots/research/rebuilds/`，只保留近期排障窗口，不覆盖正式快照。
- 开盘决策、持仓观察和复盘摘要进入 Obsidian；后续如果要量化“人工是否采纳”，再单独入仓。

## 中间层事实表

中间层不追求好看，追求能查、能聚合、能反推。当前稳定表：

| 表 | 粒度 | 用途 |
| --- | --- | --- |
| `run_manifest` | 每个目标日最新一次运行一行 | 保存该日期当前采用的运行版本和质量状态 |
| `run_manifest_history` | 每次入仓运行一行 | 按 run_id 追加保存参数、代码提交、数据覆盖和质量状态，支持完整审计 |
| `data_quality_daily` | 每个报告源每天一行 | 保存候选、情绪、主线、资金、风险、问财、复盘等数据源是否就绪 |
| `research_candidate_daily` | 每天每只最终候选一行 | 保存分层、分组、分数、主题、风险、预期观察周期、原因标签和市场态度摘要 |
| `decision_signal_daily` | 每天每只决策信号一行 | 保存 `buy_watch/upgrade_watch/hold_watch/watch/avoid` 等处理口径、置信度、观察周期、观察条件和失效条件 |
| `fundamental_watchlist_daily` | 每天每只基本面深研交接标的一行 | 保存交给 `ai-berkshire` 的优先级、建议研究技能、交接原因、核心问题、来源信号和风险标签 |
| `fundamental_quality_daily` | 每天每只交接候选的财务硬指标一行 | 按公告日做 point-in-time 截断，保存 ROE、现金利润比、负债、增长、估值、质量结论和原因标签 |
| `fundamental_research_queue_daily` | 每天正式交给深研的少量公司一行 | 从质量筛选结果中剔除 reject，控制在 5 只以内，保留量化来源和财务筛选证据 |
| `fundamental_verdict_daily` | 每次基本面深研返回的每只标的一行 | 保存 `pass/watch/reject`、质量分、估值风险、行业展望、催化周期和财务风险标签，供冻结计划读取 |
| `stock_market_attitude_daily` | 每天每只候选一行 | 保存热度、资金承接、主题共振、盘面态度、事件、风险和拥挤度，输出强确认/温和确认/冷启动/虚热/过热分歧/风险压制 |
| `candidate_lifecycle_daily` | 每个生命周期每天一行 | 观察新入池、继续、升级、降级、消失、命中、失败、移出 |
| `research_outcome_daily` | 每个信号日、每只候选一行 | 保存绝对收益、基准收益、行业同类收益和超额收益；按信号日覆盖，避免滚动复盘重复计数 |
| `missed_opportunity_daily` | 每个明显错过样本一行 | 记录当天大涨但没进入候选的票，以及 miss 原因、风险和是否可学习 |
| `factor_diagnostics_daily` | 每个复盘聚合项一行 | 保存分层、动作桶、模型桶、阶段、亏损归因、miss 可学习性的统计结果 |
| `strategy_review_daily` | 每个策略片段一行 | 把复盘统计粗标为有效、中性、拖后腿或样本不足，供后续策略反思使用 |
| `risk_event_daily` | 每天每只风险事件一行 | 保存巨潮公告结构化风险事件：事件类型、严重度、标题和来源 |
| `money_flow_daily` | 每天每只资金流一行 | 保存东财个股资金流确认因子：主力净流入、3/5 日净流入和资金分 |
| `external_screen_daily` | 每天每只外部筛选命中一行 | 保存问财 CSV 导入结果：查询条件、排名、外部评分、标签和命中原因 |

这些表由 `warehouse-backfill-snapshots` 和 `warehouse-ingest` 自动派生。风险事件、资金流、问财导入和基本面深研交接清单需要先生成同日 CSV，入仓时会自动识别。

## 三项目协作边界

- `alpha_cn`：负责全市场数据准备、形态/情绪/主线/风险筛选、候选生命周期、复盘和结构化信号输出。
- `ai-berkshire`：只消费 `fundamental_watchlist` 这类小清单，做商业质量、景气周期、估值、财报和 thesis 漂移验证，并通过 `fundamental_verdict_daily` 返回结构化结论，不做全市场扫盘。
- `Codex`：只消费 `Context Pack`、数仓视图和用户持仓，负责每日复盘、持仓交互和结论整理，不重复实现候选筛选逻辑。

`run_manifest` 和 `data_quality_daily` 是早上判断“今天能不能用”的第一入口。结构化 CSV 是数据质量判断主依据；Markdown 和 Obsidian 属于用户展示层，不决定研究数据是否可用。

候选表会写入：

- `candidate_model_version`：候选分层/动作桶规则版本。
- `factor_schema_version`：资金流、风险事件、问财导入等因子字段版本。

后续复盘某个时期的表现时，要同时看日期和版本，避免把旧规则样本和新规则样本混在一起解释。

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

## 研究可信度地基

`security_master_daily` 保存每个股票池快照日的证券状态，不用今天的股票池覆盖过去。当前字段包括市场、板块、ST/退市名称标记和当日涨跌幅制度。它从 2026-06-18 起有本项目快照历史；更早时期如果要做严格全市场回测，仍需补上市、退市、历史 ST 和行业成分的权威 point-in-time 数据。

`run_manifest` 会固化：

- 数据截止日和计划日
- Git commit 与工作区是否未提交
- 参数 JSON 与 SHA-256 参数哈希
- 每个输入报告的状态、行数和内容指纹
- 必需数据和增强数据的覆盖情况

空表不再视为 `OK`。核心表为空标记 `FAIL`，资金流、问财等增强表为空标记 `WARN`。

历史地基统一回填：

```powershell
python -m quant_a_stock.cli warehouse-backfill-foundation --since 2026-06-12 --until 2026-07-09
```

这个命令会回填 `security_master_daily`、`decision_signals`、`decision_signal_daily`，并重建带版本、原因标签和预期周期的生命周期日表。生命周期按真实 `target_date` 分区覆盖，避免每日运行重复累计整段历史。
