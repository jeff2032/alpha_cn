# Windows 命令行约定

这个项目在 Windows 上长期跑，命令行尽量走固定入口，少临时拼复杂 PowerShell。

## 固定入口

项目常用操作统一走：

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\scripts\alpha.ps1 <command>
```

常用命令：

```powershell
.\scripts\alpha.ps1 task-status
.\scripts\alpha.ps1 latest-ops
.\scripts\alpha.ps1 obsidian-tree
.\scripts\alpha.ps1 cache-status -TargetDate 2026-06-22
.\scripts\alpha.ps1 warehouse-status
.\scripts\alpha.ps1 data-loop -TargetDate 2026-06-22 -PlanDate 2026-06-23
.\scripts\alpha.ps1 retention-plan
.\scripts\alpha.ps1 daily -TargetDate 2026-06-22 -PlanDate 2026-06-23
```

## 日常原则

- 业务逻辑尽量放在 `python -m quant_a_stock.cli ...` 或项目脚本里。
- PowerShell 只做编排、查询、文件复制和 Windows 计划任务操作。
- 长命令不要临时拼，沉淀到 `scripts/*.ps1`。
- 读取状态优先用 `scripts/alpha.ps1`，减少一次性复杂命令。
- 写 Obsidian、计划任务这类项目外目录时，要明确目标路径。

## 避坑记录

PowerShell 顶层 `foreach { ... } | Format-Table` 容易写出空管道错误。标准写法是先收集再输出：

```powershell
$rows = foreach ($item in $items) {
    [pscustomobject]@{ Name = $item.Name }
}
$rows | Format-Table -AutoSize
```

Windows 计划任务不要假设一定有 `Rename-ScheduledTask`。需要改名时，更稳的是：

1. 读取旧任务的 Action / Trigger / Settings / Principal。
2. 用新名字 `Register-ScheduledTask`。
3. 确认新任务存在。
4. `Unregister-ScheduledTask` 删除旧任务。

Codex 里并行跑多个 PowerShell 进程偶尔会遇到 `CreateProcessAsUserW failed: 1312`。遇到这种情况按顺序单条执行，不影响项目本身。

Windows PowerShell 5.1 对无 BOM 的 UTF-8 脚本不稳定。如果 `.ps1` 里包含中文路径、中文输出或中文文件名，统一保存为 UTF-8 with BOM。否则可能出现看起来很怪的报错，比如字符串没闭合、中文路径附近语法错误。

## 当前推荐工作流

晚上自动：

```powershell
.\scripts\alpha.ps1 task-status
```

确认 `AlphaCN Nightly Prep` 每天 16:30 会跑。

早上手动：

```powershell
.\scripts\alpha.ps1 latest-ops
.\scripts\alpha.ps1 obsidian-tree
```

需要重新生成开盘决策、持仓观察和复盘摘要时：

```powershell
.\scripts\alpha.ps1 daily
```

需要检查数据闭环和清理预案时：

```powershell
.\scripts\alpha.ps1 data-loop
.\scripts\alpha.ps1 retention-plan
```
