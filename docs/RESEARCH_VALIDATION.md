# 回测、因子证据与影子组合

这一层只验证研究结论，不连接券商，不产生实盘委托。

## 真实成交回测

普通 `backtest` 默认使用 `realistic` 模式：信号在收盘后形成，下一交易日开盘撮合。

成交模型包含：

- 次日开盘价成交和滑点
- 停牌不可成交
- 涨停不可买、跌停不可卖
- 100 股整手
- 最低佣金、买卖佣金、印花税和过户费
- T+1 日线约束

`BacktestConfig(execution_model="simple")` 可保留旧比例回测作为快速对照，但正式验证以 `realistic` 为准。

组合默认约束：单票 15%、总仓位 80%、同一行业/主题 30%。可在 `research-backtest`、walk-forward 和影子组合命令中调整。

影子组合还使用市场环境仓位门：强势 80%、震荡偏强 60%、震荡 40%、防守/未知 20%。当宽基指数出现 1/3/5 日快速下跌时会立即降到防守档，不等待 20/60 日趋势完全转弱。

## Walk-forward 样本外验证

```powershell
python -m quant_a_stock.cli research-walk-forward --years 3 --train-days 252 --test-days 63 --step-days 63 --embargo-days 5 --top-ns 5,10,20 --min-scores 45,50,55 --max-ret-20s 0.15,0.20,0.25
```

每一折只在训练窗选择参数；训练窗和测试窗之间留出 embargo；最终只汇总测试窗表现。重点看正收益折占比、平均 OOS 收益、最差回撤和参数稳定性，不再用全区间最优参数自证。

## 因子证据

```powershell
python -m quant_a_stock.cli factor-evidence --since 2026-06-12 --until 2026-07-09 --horizon 5d --quantiles 5
```

当前只研究已有因子：低位程度、量能、20/60 日涨幅、多周期、主题强度、拥挤度和公告风险。统一输出：

- 每日截面 Spearman IC
- IC 均值、波动和正 IC 比例
- 五分位收益及单调性
- 最高分组换手
- 强势、震荡、弱势市场中的超额收益和胜率

行业和市场结果使用 `research_outcome_daily` 的 point-in-time 复盘事实。没有历史字段的日期保持缺失，不用今天的数据补过去。

少于 40 个完整截面日期只做诊断，40-59 个日期只允许候选验证，达到 60 个日期后才进入正式因子调权评审。

## 影子组合

每天开盘前冻结计划：

```powershell
python -m quant_a_stock.cli shadow-freeze --target-date 2026-07-09 --plan-date 2026-07-10 --top 10
```

冻结文件位于：

```text
data/shadow/plans/plan_date=YYYY-MM-DD/plan.csv
```

默认拒绝覆盖已经冻结的计划，防止盘后修改历史判断。收盘后重放成交和净值：

```powershell
python -m quant_a_stock.cli shadow-evaluate --until 2026-07-10
```

默认使用 `stateful` 状态化组合：新计划只补空余席位；已持仓标的至少走完所属信号的最短观察期，再根据是否继续入选决定退出；达到最长周期强制退出；完整退出后默认冷却 3 个交易日。市场仓位上限变化超过 2 个百分点时才减仓，避免每天因排名和目标权重小幅变化反复交易。

输出包含成交受阻原因、成交原因、成交数量、费用、每日净值、持仓权重和持有天数。需要复现旧的“每天完全切换到最新名单”逻辑时使用 `--mode daily_target`。

历史快照回填并按次日开盘重放：

```powershell
python -m quant_a_stock.cli shadow-backfill --since 2026-06-15 --until 2026-07-10 --top 10 --signal-top 80
```

回填严格读取当日已经冻结的研究快照，不用未来字段修饰过去。每天最多 10 只；有效标的不足 5 只时允许少于 5 只或全现金，不为凑数量放宽风险规则。命令会同时计算 `stateful` 与 `daily_target`，比较收益、最大回撤、交易次数、费用和平均持仓数；主报告默认保存状态化结果。

可调整状态化参数：

```powershell
python -m quant_a_stock.cli shadow-evaluate --mode stateful --max-positions 10 --cooldown-days 3 --rebalance-tolerance 0.02
```

基本面结论是可选增强。导入 `ai-berkshire` 回流文件后，可在冻结时传入：

```powershell
python -m quant_a_stock.cli shadow-freeze --target-date 2026-07-10 --plan-date 2026-07-13 --fundamental-verdict-report reports/fundamental_verdicts_20260710_HHMMSS.csv
```

`reject` 阻止新入组合，`pass` 和 `watch` 在同类技术信号内调整优先级；没有基本面结论的标的仍按量化信号正常处理。

当前动作周期统一为：A2 主攻 3-5 日、B2 升级观察 3-5 日、A3 短线 1-3 日；B1 只保留为内部对照，不进入影子组合。

每日脚本会自动冻结下一交易日计划；夜间脚本会更新影子组合收盘估值和 5 日因子证据。
