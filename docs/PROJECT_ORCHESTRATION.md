# AlphaCN、Daily Stock Analysis 与 AI Berkshire 协作运维

## 职责边界

三个项目不重复做同一件事：

| 项目 | 唯一职责 | 常驻方式 |
|---|---|---|
| AlphaCN | 行情、主题、风险、量化候选、生命周期、回测、影子组合 | `AlphaCN Nightly Prep` 每天 16:30 |
| Daily Stock Analysis | Web/API、单股解读、持仓辅助、历史报告和通知 | 用户登录后启动 Server |
| AI Berkshire | 少量重点公司的商业质量、财务、估值和 thesis 深研 | Codex Skills，按需调用 |

AI Berkshire 不是服务器，不需要后台常驻。安装到 Codex 后，发现新的 `fundamental_watchlist` 时再调用深研，最后按 `config/fundamental_verdicts.example.csv` 返回 `pass/watch/reject`。

## 每日数据流

```text
AlphaCN 夜间准备
  -> DecisionSignal / Context Pack
  -> fundamental_watchlist（少量基本面问题）
  -> AI Berkshire 按需深研
  -> import-fundamental-verdicts
  -> AlphaCN 冻结最终计划
  -> dsa-handoff 提交 5-8 只重点标的
  -> DSA 生成人能阅读的单股分析、持仓辅助和通知
```

DSA 只接收 `buy_watch` 和 `upgrade_watch`，并过滤中高风险标的。没有合格标的时输出空交接，不为凑数量提交。

## 开机启动

当前计划任务：

- `AlphaCN Nightly Prep`：每天 16:30 运行慢数据和研究准备。
- `AlphaCN Daily Stock Analysis`：用户登录 30 秒后启动 DSA Web/API。

重新注册 DSA 开机任务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\register_research_services.ps1
```

手动启动或修复服务：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\start_daily_stock_analysis.ps1
```

DSA 地址：<http://127.0.0.1:8000>

## DSA 首次配置

服务在线不代表模型已经就绪。首次打开 DSA 后，在 Settings 中至少配置一个可用 LLM Provider。当前机器没有检测到系统级 OpenAI、Gemini、DeepSeek 或 Anthropic Key，Hermes `127.0.0.1:8642` 也未启动，所以在完成设置前不要自动提交分析任务。

DSA 自己的 scheduler 保持关闭。全市场研究由 AlphaCN 负责，AlphaCN 只把少量最终候选提交给 DSA，避免两个调度器重复下载和分析。

## 交接命令

先预览，不提交：

```powershell
python -m quant_a_stock.cli dsa-handoff --top 8
```

DSA 模型配置完成后提交异步分析：

```powershell
python -m quant_a_stock.cli dsa-handoff --top 8 --submit
```

默认不发送通知。需要 DSA 同步推送时显式增加 `--notify`。

交接事实保存到：

```text
data/context/dsa/数据截至日/plan_计划日期.json
```

## AI Berkshire

官方 Skills 和快捷 prompts 已安装到：

```text
%USERPROFILE%\.codex\skills
%USERPROFILE%\.codex\prompts
```

重启 Codex 后生效。常用入口包括：

- `investment-research`：单公司完整研究。
- `investment-team`：多 Agent 交叉研究。
- `earnings-review`：财报复盘。
- `thesis-drift`：持仓逻辑漂移检查。
- `portfolio-review`：组合复盘。

AI Berkshire 的结论回流：

```powershell
python -m quant_a_stock.cli import-fundamental-verdicts --input path\to\verdicts.csv --target-date YYYY-MM-DD
```

## 健康检查

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\check_research_services.ps1
```

检查内容包括夜间任务、DSA 开机任务、DSA 健康接口、最新 Context Pack、AI Berkshire Skills 和 DSA 模型配置状态。

## 重建 DSA 环境

首次安装或虚拟环境损坏时：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\bootstrap_daily_stock_analysis.ps1
```

Windows 约束文件固定 `litellm 1.82.6 + tiktoken 0.11.0`。原因是 DSA 当前要求 `tiktoken <0.12`，而 LiteLLM 1.83 及以上要求 `tiktoken 0.12`。
