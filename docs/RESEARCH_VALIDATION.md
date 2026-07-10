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

输出包含成交受阻原因、成交数量、费用、每日净值、持仓权重和持有天数。达到预期周期上限、下一份计划移除或目标权重归零时，按下一可成交开盘退出。

每日脚本会自动冻结下一交易日计划；夜间脚本会更新影子组合收盘估值和 5 日因子证据。
