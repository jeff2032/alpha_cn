# AlphaCN、Codex 与 AI Berkshire 每日研究工作流

## 职责边界

当前项目采用两层系统和一组深研能力：

| 组件 | 职责 | 是否常驻 |
|---|---|---|
| AlphaCN | 行情、主题、风险、量化候选、生命周期、回测、影子组合和数仓 | 每天 16:30 自动运行 |
| Codex | 读取结构化事实、复盘策略、分析持仓、讨论风险、生成用户决策结论 | 用户使用时运行 |
| AI Berkshire Skills | 商业质量、财报、估值、管理层和 thesis 深研 | 由 Codex 按需调用 |

Codex 不替代 AlphaCN 的量化计算，也不把对话当数据库。可复现事实继续保存在 DuckDB、Parquet、每日快照和候选生命周期中；用户结论继续写入 Obsidian。

## 每日节奏

### 收盘后

`AlphaCN Nightly Prep` 从 16:30 开始：

1. 增量补充日线行情。
2. 更新行业、主题、公告风险、资金流和情绪缓存。
3. 生成候选池、DecisionSignal、Context Pack 和数仓中间层。
4. 失败时保留运维报告，不静默生成不完整结论。

### 早上与 Codex 一起复盘

先检查底座：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_codex_research_ready.ps1
```

需要刷新用户结论层时：

```powershell
.\scripts\alpha.ps1 daily
```

然后在 Codex 中直接提出研究任务，例如：

```text
检查最新交易日数据是否完整。基于最新 Context Pack、生命周期、影子组合和昨日实际表现，
先复盘策略，再给出下一交易日的主攻、短线、持有观察和风险失效条件，并同步 Obsidian。
```

Codex 应优先读取：

1. `data_quality_daily` 和 `run_manifest`，判断数据能否使用。
2. 最新 Context Pack 和 DecisionSignal，确定当日量化事实。
3. `candidate_lifecycle_daily`，避免把连续多日同一标的重复当成新推荐。
4. 影子组合和历史复盘，判断信号是否能转化为可成交结果。
5. Obsidian 仅输出用户需要决策的短结论。

## AI Berkshire 深研

AI Berkshire 已安装为 Codex Skills，不作为独立服务器运行。以下情况才调用：

- A2 主攻或真实持仓进入关键决策点。
- 公告、财报或估值变化可能改变持有逻辑。
- 需要核查商业质量、管理层、竞争壁垒或 thesis 漂移。

常用 Skills：

- `investment-research`：单公司完整研究。
- `investment-team`：多 Agent 交叉研究。
- `earnings-review`：财报复盘。
- `thesis-drift`：持仓逻辑漂移检查。
- `portfolio-review`：组合复盘。

AlphaCN 继续通过以下命令生成少量深研清单：

```powershell
python -m quant_a_stock.cli fundamental-watchlist --target-date YYYY-MM-DD --plan-date YYYY-MM-DD --top 10
```

AI Berkshire 的结论按 `config/fundamental_verdicts.example.csv` 回流：

```powershell
python -m quant_a_stock.cli import-fundamental-verdicts --input path\to\verdicts.csv --target-date YYYY-MM-DD
```

`reject` 阻止新进入影子组合，`pass/watch` 只调整同类量化信号的优先级，不替代技术和市场环境规则。

## 持仓交互

持仓问题优先采用交互式分析，而不是自动生成固定长文：

```text
读取我的最新持仓和成本，结合最新量化信号、公告风险、市场主线和生命周期，
逐只给出继续持有、减仓观察、等待确认或退出的条件。不要只根据盈亏比例判断。
```

分析必须明确：

- 数据截至哪一天。
- 当前市场环境和总仓位建议。
- 每只股票的有效逻辑、观察条件和失效条件。
- 哪些结论来自量化事实，哪些属于基本面判断或推断。

## 持久化原则

- 对话负责理解和讨论，不承担历史存储。
- DuckDB + Parquet 保存机器可复盘事实。
- Context Pack 保存当次研究上下文。
- Obsidian 保存给用户看的开盘决策、持仓观察和复盘摘要。
- 任何历史复盘都使用当时可获得的数据，不用今天的信息改写过去。
