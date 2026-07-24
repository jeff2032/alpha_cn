# 每日选股研究流程

这个流程用于每天收盘后做 A 股候选池研究。目标是选出少量值得人工复盘的股票，而不是直接生成买卖指令。

## 每天固定流程

现在分成两段：

- 晚上慢准备：16:30 由一个定时任务连续跑，适合放所有耗时、可能卡接口的事情，包括行情补数、全市场形态扫描、情绪、市场主线、公司资料和公告风险。
- 早上快决策：不再逐只联网查公告/公司资料，只用昨晚准备好的缓存和报告，快速生成计划、复盘和策略反思。

## 晚上慢准备

先确认数据是否更新到最近交易日：

```powershell
python -m quant_a_stock.cli cache-date-status --universe-file data/universe/a_stock.csv --show-stale --top 30 --output-stale data/universe/stale.csv
```

如果有过期标的，只补过期标的：

```powershell
python -m quant_a_stock.cli sync-stock-universe --universe-file data/universe/stale.csv --since 2020-01-01 --stock-provider sina --adjust qfq --incremental --lookback-days 60 --workers 6 --sleep 0.05 --no-skip-existing
```

扫描全市场突破确认池：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern base_breakout_setup --top 160 --min-score 45 --stages watch near_breakout --min-amount-ma20 100000000 --require-positive-trend-slope --max-close-vs-trend 0.25 --filter-max-ret-20 0.25
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

扫描全市场强趋势回踩/再启动池：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern trend_pullback_setup --top 160 --min-score 45 --stages trend_pullback trend_resume --min-amount-ma20 100000000 --min-ret-60 0.18 --filter-max-ret-20 0.18 --max-volume-ratio 3.20 --max-close-vs-trend 0.65 --max-drawdown-from-high 0.32
```

趋势回踩池对应日报里的 A3：它用于捕捉已经有 60 日趋势、近 20 日不过热、回撤后重新企稳的候选。A3 只有在主线仍强、风险干净、位置不拥挤时才进入主攻，否则只放在高波动观察池。

扫描静默反转观察池：

```powershell
python -m quant_a_stock.cli scan-pattern --pattern quiet_reversal_setup --top 80 --min-score 55 --min-amount-ma20 100000000
```

静默反转只观察“前 20 日偏弱、120 日位置较低、量能收缩、最近 5 日开始企稳”的样本。报告会归档为 `scan_quiet_reversal_setup_*.csv`，但不会合并进主候选池；先累计 1/3/5 日证据，避免用次日涨停样本反向放宽主模型。

日常入口会把 base/trend 两类扫描放宽到 45 分，但低分样本只进入 B2 观察池；A1 按 10-20 日潜伏观察，A2 是 3-5 日主攻，A3 只做 1-3 日短线确认，B2 必须在 3-5 日内升级，B1 不再进入推荐层。高风险直接回避，中高风险只保留为风险待核，不进入主攻或影子组合。

给形态候选池做情绪评分：

```powershell
python -m quant_a_stock.cli sentiment-score --latest-scan --target-date 2026-06-12 --top 90 --display-top 30 --news-days 7
```

生成市场主线：

```powershell
python -m quant_a_stock.cli market-theme --target-date 2026-06-12 --top 20
```

生成资金流、巨潮风险和问财外部验证：

```powershell
python -m quant_a_stock.cli money-flow --latest-scan --target-date 2026-06-12 --top 90 --display-top 30 --retries 3 --retry-wait 2 --sleep 0.4 --min-success-rate 0.6
python -m quant_a_stock.cli risk-events --latest-scan --target-date 2026-06-12 --top 90 --days 180 --display-top 30
python -m quant_a_stock.cli import-iwencai --file exports/iwencai/2026-06-12.csv --target-date 2026-06-12 --query "低位放量 半导体"
```

这三类报告会写成 `money_flow_*.csv`、`risk_events_*.csv` 和 `iwencai_import_*.csv`。`research-candidates` 会严格按同一目标日期自动合并它们；如果当天没有对应报告，就跳过，不使用其他日期兜底。
其中资金流报告有成功率保护：接口失败太多时不写正式报告，夜间慢任务会软失败继续往下跑。

合成最终研究候选池：

```powershell
python -m quant_a_stock.cli research-candidates --target-date 2026-06-12 --top 30
```

从候选池派生结构化决策信号：

```powershell
python -m quant_a_stock.cli decision-signals --target-date 2026-06-12 --plan-date 2026-06-15 --top 80
```

`decision_signals_*.csv` 是机器事实层，不是新的推荐模型。它把候选拆成 `buy_watch`、`upgrade_watch`、`hold_watch`、`watch`、`avoid`，并写入置信度、观察周期、观察条件和失效条件，供持仓辅助、Context Pack 和后续复盘使用。

导出给 `ai-berkshire` 做基本面深研的小观察清单：

```powershell
python -m quant_a_stock.cli fundamental-watchlist --target-date 2026-06-12 --plan-date 2026-06-15 --top 20
```

`fundamental_watchlist_*.csv` 不是新的选股模型，也不是用户直接看的荐股页。它从 `decision_signals` 中挑少量更值得验证基本面的标的，写入优先级、建议使用的 `ai-berkshire` 研究技能、交接原因和需要回答的问题。对应 JSON 会写到 `data/context/fundamental/数据截至日/ai_berkshire_plan_计划日期.json`。

这里的 `investment-checklist`、`investment-research`、`thesis-tracker` 等技能只是结构化交接建议，不会在夜间量化任务中自动执行，也不会直接改变技术分数。Codex/AI Berkshire 只对少量候选调用这些技能，核验商业质量、财务风险、估值和投资论文，再把 `pass/watch/reject` 结论回流给 AlphaCN。

交接给 AI Berkshire 前先运行财务硬指标去劣：

```powershell
python -m quant_a_stock.cli fundamental-quality-screen --target-date 2026-07-23 --top 20 --research-top 5 --workers 4 --refresh
```

命令只对最多 20 只候选抓取公开财务指标，并缓存到 `data/cache/akshare/fundamentals/`。计算时按公告日期截断到 `target-date`，历史回跑不会读取当时尚未披露的财报。输出包括：

- `fundamental_quality_screen_*.csv`：全部候选的 ROE、现金利润匹配、负债、增长、PE/PB、质量分和扣分原因。
- `fundamental_quality_review_details_*.csv`：历史时点财务质量结论及下一交易日开盘后的 3/5/10/20 日收益。
- `fundamental_quality_review_summary_*.csv`：按通过、观察、否决、专用模型汇总的收益和超额收益证据。

历史检验命令：

```powershell
python -m quant_a_stock.cli fundamental-quality-backfill --since 2026-06-15 --until 2026-07-23 --top 20 --signal-top 80 --workers 6 --no-refresh --benchmark-symbol 510300
```

财务质量层的职责是分配深研资源和执行明确风险否决，不参与 A2/A3 短周期候选的重新排序。只有深研结论为 `reject` 时才从影子组合和用户主攻区移除；`pass/watch` 不代表未来 3 至 20 日收益更高。

行业模型按候选层的 point-in-time 行业字段路由：

- 银行：重点看 ROE、不良率、拨备覆盖率和核心一级资本充足率，不用普通企业资产负债率硬判。
- 券商：重点看 ROE、杠杆、收入和利润周期，显式保留市场周期风险。
- 煤炭：保留通用质量判断，同时强制标记煤价、产量和资本开支周期复核。
- 半导体及电子设备：提高对成长与毛利的权重，现金转化弱只作成长阶段警示，但低 ROE 且缺少收入成长仍可否决。
- `fundamental_research_queue_*.csv`：去掉 `reject` 后最多 5 只正式深研队列。
- `specialized_review`：银行、券商、保险和信托不套用通用企业规则，留给专用模型。

质量筛选的职责是排除明显低质量或数据不足样本。深研队列以财务质量为主体，叠加量化研究优先级，并对明显偏高的 PE/PB 做排序降权；估值偏高不会直接否决，低 PE 也不会自动选入。最终仍由 AI Berkshire 判断商业模式、护城河、管理层和安全边际。

`ai-berkshire` 完成深研后，只需按 `config/fundamental_verdicts.example.csv` 返回结构化结论。AlphaCN 不复制财务分析过程，只接收结论：

```powershell
python -m quant_a_stock.cli import-fundamental-verdicts --input path/to/verdicts.csv --target-date 2026-07-10
```

命令会规范化 `pass/watch/reject`、质量分和风险摘要，写入 `fundamental_verdict_daily`。影子组合冻结时可显式读取该报告；基本面回流缺失不会阻塞每日量化流程。

收口阶段也可以用统一研究流水线一次完成：

```powershell
python -m quant_a_stock.cli research-pipeline --target-date 2026-06-12 --plan-date 2026-06-15 --top 30 --signal-top 80 --fundamental-top 20 --no-write-warehouse
```

这条命令只做 `alpha_cn` 的研究内核收口：归档快照、生成每日复盘、派生决策信号、导出基本面深研交接清单、导出 Context Pack，可选入仓。它不在量化流水线里生成主观 AI 结论；每日解读、持仓讨论和策略反思由 Codex 交互层完成。

导出给 AI 解读、Web 壳或其他项目读取的结构化上下文：

```powershell
python -m quant_a_stock.cli export-context-pack --target-date 2026-06-12 --plan-date 2026-06-15 --top 30
```

Context Pack 写入 `data/context/research/数据截至日/plan_计划日期.json`，内容包括市场口径、主线、候选分层、决策信号、基本面深研交接清单、复盘摘要、生命周期和本地持仓匹配。它是机器可读接口，不替代 Obsidian 的用户决策页；Codex 读取这层 JSON 做每日复盘、持仓交互和结论整理，AI Berkshire Skills 只对少量重点标的做深研。

夜间版本会抓公司资料、公告风险、巨潮结构化风险事件和东财资金流，允许慢慢跑。它会先补基础行情；如果补完后过期标的超过阈值，默认 30 只，会在同一个任务里等待并重试，默认最多 6 轮、每轮间隔 30 分钟；仍未达标时才跳过后续慢分析并写运维报告。手动执行完整夜间准备：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_nightly_research_prep.ps1
```

归档当天快照：

```powershell
python -m quant_a_stock.cli snapshot-research --target-date 2026-06-12
```

生成每日中文复盘报告：

```powershell
python -m quant_a_stock.cli daily-research-summary --target-date 2026-06-12 --top 30
```

生成候选池滚动复盘报告：

```powershell
python -m quant_a_stock.cli research-review --since 2026-05-29 --until 2026-06-12 --top-movers 20
```

这个报告会把历史快照里的候选池和 1/3/5/10/15/20/30 个交易日表现对齐。默认策略评价改读独立生命周期：A3 看 1-3 日，A2 看 3-5 日，A1 保留 10-30 日研究窗口，B2 统一看 3-5 日内能否升级；每日重复信号只作诊断。

生成 A1/A2/A3/B2 候选生命周期跟踪：

```powershell
python -m quant_a_stock.cli track-candidates --since 2026-05-29 --until 2026-06-12 --top 50
```

这个报告会把“选进去之后怎么走”独立记录下来：新入池、继续跟踪、升级、降级、消失、命中、失败和观察窗口收益。它会写入 `candidate_lifecycles` 与 `candidate_lifecycle_daily` 两张仓库表，后续复盘和因子研究优先读这里。人工报告只展示主攻继续跟踪、观察继续跟踪、今日变化、命中待复核和失败/移出，系统内部仍保留全量生命周期。

复盘报告里的“明显错过样本和风险提示”要分开看：

- `次日涨幅超常规涨跌幅`：优先按复权、除权或特殊事件样本处理，不拿来直接优化选股规则。
- `未做公告风险核验`：说明该票没有进入最终候选池，尚未检查公告、质押、减持、问询等风险，不能因为次日大涨就追高。
- `120 日区间位置偏高`、`前 20 日涨幅偏高`、`信号日放量过猛`：更偏右侧追涨风险，只能放主线补票观察。
- `20 日成交额偏低`、`次新或历史样本不足`：流动性和样本可靠性不足，原则上不纳入常规升级观察池。

把当晚最新报告写入研究仓库：

```powershell
python -m quant_a_stock.cli warehouse-ingest --target-date 2026-06-12
```

仓库采用 DuckDB + Parquet，落在 `data/warehouse/`，这个目录不提交 git。当前分三层使用：Obsidian 只放用户能看懂的结论；DuckDB/Parquet 保存 `research_candidate_daily`、`decision_signal_daily`、`fundamental_watchlist_daily`、`stock_market_attitude_daily`、`candidate_lifecycle_daily`、`missed_opportunity_daily`、`factor_diagnostics_daily`、`strategy_review_daily` 等中间层事实表；行情、主题、公告和快照保留为原始底座。

把股票池写入维表：

```powershell
python -m quant_a_stock.cli warehouse-sync-universe --universe-file data/universe/a_stock.csv --target-date 2026-06-12
```

把本地日线 CSV 缓存同步成 Parquet：

```powershell
python -m quant_a_stock.cli warehouse-sync-candles --universe-file data/universe/a_stock.csv --target-date 2026-06-12
```

日线行情同步是增量式的：如果某只股票 Parquet 里已经到达 CSV 的最后日期，会标记为 `skipped`，不会每天重写全量历史。第一次初始化会比较慢，后面夜间同步会轻很多。

回填历史研究快照：

```powershell
python -m quant_a_stock.cli warehouse-backfill-snapshots --since 2026-06-12 --until 2026-06-18
```

查看仓库覆盖：

```powershell
python -m quant_a_stock.cli warehouse-status
```

查看今天数据是否适合用于决策：

```powershell
python -m quant_a_stock.cli warehouse-query --table run_manifest --columns run_id,target_date,plan_date,quality_status,missing_required,warning_reports --limit 5
python -m quant_a_stock.cli warehouse-query --table data_quality_daily --columns target_date,source_group,report_type,quality_level,issue --since 2026-07-01 --limit 80
```

`quality_status = READY` 说明结构化数据闭环完整；`WARN` 通常是增强源缺失或可展示层缺失；`FAIL` 表示候选、情绪、主线、每日候选或复盘等必需结构化数据缺失，先补数据再做决策。

按日期区间汇总复盘：

```powershell
python -m quant_a_stock.cli warehouse-review --since 2026-06-12 --until 2026-06-18
```

夜间准备状态会写到：

- `reports/ops/nightly_prep_*.md`
- `logs/nightly_prep/`

## 早上快决策

早上不跑慢公告/资料接口，直接执行：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\run_daily_research.ps1
```

早上脚本会做一次快速刷新和报告导出，并把 Markdown 同步到 Obsidian：

- 开盘决策：`中国A股荐股/开盘决策/计划日期.md`
- 持仓观察：`中国A股荐股/持仓观察/计划日期.md`
- 复盘摘要：`中国A股荐股/复盘摘要/数据截至日.md`

Obsidian 是用户结论层，只放少量可读结论。完整候选、情绪、滚动复盘、生命周期明细继续保留在项目内部 `reports/` 与 DuckDB/Parquet。

开盘决策按计划交易日命名。推荐、观察和风险条件可以以计划交易日为主语；但市场温度、市场主线、滚动复盘、生命周期状态这类已经发生的事实，要以数据截至日为主语。例如 `2026-07-02` 的开盘决策里，市场主题应写成 `2026-07-01 收盘主线回顾`，市场判断应写成 `2026-07-01 收盘市场口径`，避免把上一交易日事实误读成计划日预测。

日期参数的含义固定为：

- `TargetDate`：数据截至日。
- `PlanDate`：开盘计划日。
- `2026-07-07` 开盘计划应基于 `2026-07-06` 收盘后数据，即 `-TargetDate 2026-07-06 -PlanDate 2026-07-07`。
- 不手工传 `PlanDate` 时，脚本默认生成 `TargetDate` 之后的下一个交易日计划。

持仓观察读取本地 `data/manual/holdings.csv`，字段参考 `config/holdings.example.csv`。真实持仓只存在本机，`data/` 不提交 git。

它默认使用：

```powershell
python -m quant_a_stock.cli research-candidates --target-date 目标日期 --top 30 --no-fetch-profiles --no-fetch-notices
```

这样即使慢接口不稳定，也不会卡住早上的荐股和复盘。

## 每天主要看哪些报告

用户优先看：

- `中国A股荐股/开盘决策/YYYY-MM-DD.md`：机会、主攻、观察和失效条件。
- `中国A股荐股/持仓观察/YYYY-MM-DD.md`：已有持仓处理口径。
- `中国A股荐股/复盘摘要/YYYY-MM-DD.md`：上一交易日一页短复盘。

我们内部复盘再看：

- `daily_research_summary_*.md`：每日主报告，综合市场温度、主线、候选分层、持续性和风险提醒。
- `research_candidates_*.md`：最终候选池，优先看 `action_bucket`，再看 A1/A2/A3/B2 分层。
- `fundamental_watchlist_*.csv`：给 `ai-berkshire` 的基本面深研交接小名单，主要看优先级、研究技能和问题清单。
- `research_review_*.md`：滚动策略复盘，重点看主攻池、升级观察池、观察池近期命中、错过和亏损样本。
- `candidate_lifecycle_tracking_*.md`：A1/A2/A3/B2 候选生命周期，重点看入池后是否升级、兑现、失败或退出；这是内部复盘材料，不再作为 Obsidian 日常入口展示。
- `market_theme_*.md`：当天市场主线。
- `sentiment_watchlist_*.md`：候选股情绪细节。

辅助看：

- `scan_accumulation_setup_*.csv`：潜伏池形态候选。
- `scan_base_breakout_setup_*.csv`：纯形态候选。
- `scan_trend_pullback_setup_*.csv`：强趋势回踩/再启动候选。
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

- `action_bucket = 主攻-A2启动确认`：启动确认主攻池，看突破后承接、回踩不破和量能不过热。
- `action_bucket = 短线-A3一三日确认`：只按 1-3 日短线处理，不作为默认中线持有。
- `action_bucket = 升级-B2三五日观察`：3-5 日内升级到 A2/A3 才继续，否则移出。
- `action_bucket = 移出-B1无持续性`：只保留内部对照事实，不进入推荐和影子组合。
- `action_bucket = 观察-B2b主题待确认`：有主题线索但确认不足，只观察是否补量、补承接或升级。
- `research_score` 靠前，且 `risk_level` 为低或中。
- `matched_theme` 命中当天强主线，或同主题/行业候选数量明显靠前。
- `total_penalty` 低，`risk_notice_titles` 为空或只是常规披露。

谨慎观察：

- `action_bucket = 观察-A1低位潜伏`：不作为主攻，只看后续是否补量、补主题、补资金确认。
- `action_bucket = 观察-A3高波动`：趋势仍强，但高位/过热/回撤风险需要先处理。
- `action_bucket = 回避-风险优先`：原则上不进明日主攻池。
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
- 最新一组 `scan_trend_pullback_setup_*.csv`
- 最新一组 `sentiment_watchlist_*.md/.csv`
- 最新一组 `market_theme_*.md/.csv`
- 最新一组 `research_candidates_*.md/.csv`
- 最新一组 `fundamental_watchlist_*.csv`
- 最新一组 `daily_research_summary_*.md`
- 最新一组 `daily_research_candidates_*.csv`
- 最新一组 `research_review_*.md/.csv`
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

## 相对收益复盘

滚动复盘默认使用 `510300` 作为市场基准：

```powershell
python -m quant_a_stock.cli research-review --since 2026-06-12 --until 2026-07-09 --benchmark-symbol 510300
```

明细和汇总会同时保留：

- 标的绝对收益
- 基准收益与基准超额收益
- 同日同行业已知候选的等权收益与行业超额收益
- 超额胜率

当前行业收益是 point-in-time 候选池内同行业其他标的的可用样本基准，不是完整行业指数；同行样本不足时留空。后续接入完整历史行业成分后，可以平滑替换基准来源。

每日 Obsidian 导出结束后会核验 `复盘摘要`、`开盘决策` 和 `持仓观察`。缺失时任务会失败，并在 `reports/ops/obsidian_missing_*.md` 留下中文告警，不再静默跳过。
