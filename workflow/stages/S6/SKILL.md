---
name: workflow-stage-s6
description: Close an accepted delivery, clean workflow-owned temporary resources, and retain useful evidence.
---

# S6 完成归档

仅当所有目标项目都已合并或已完成无 MR 验收时执行。
开始前运行 `metrics-start` 并读取本阶段启用的静态挂载技能。

## 动作

1. 对本轮交付运行 `delivery-check <id>`，核对当前摘要、版本和验证一致；进入归档后更新摘要时重新复核并 `delivery-record <id>`。仅有历史材料且尚无快照的旧归档记为 UNVERIFIED，不因此重新实施或制造验收。按证据更新项目行、顶层阶段及唯一的 `## 当前状态摘要`，不因归档推断已合入或已上线。
2. 逐条核对 `state.md` 的 `## 资源当前清单`，仅清理归属与既有清理授权明确、精确路径和 Git 状态均核验安全的资源；未知归属或未知文件保留。对已登记且确认由本需求生成的可再生缓存，可在既有授权内精确清理；ignored 标记本身不是删除授权。清理后再次确认工作树状态为空，才非强制移除 worktree。
3. 保留任务产物；每个资源更新当前清理状态、最后核验时间与结果依据。存在待人工项不阻止已验收需求归档，但摘要清理状态必须为 PENDING/RETAINED/UNKNOWN 等真实值，不能据正文历史推断当前残留。
4. 只有经过验证、预计会在后续同类需求复用的经验才写入技能候选；一次性事实留在任务产物。候选由人类审阅后移入 `skills/` 并登记到 `config/skills.md`，不会自动挂载。
5. 汇总并完成 S6 的 `metrics.md` 记录，确认 S1～S6 每个实际进入过的环节都有一条记录；Codex/OMP 自动采集或历史回填仍无法取得精确 token 时明确保留 `NOT_AVAILABLE`。

## 输出与完成判据

- `state.md` 顶层、项目行及唯一当前摘要相符；生命周期、关闭原因、交付形态、人工验收、合入、部署与清理分别有证据，字段定义见 `workflow/protocol.md`。
- 临时分支与 worktree 均明确为已清理或待人工。
- `work/<id>/` 保留作为审计与接管依据。
- `metrics.md` 完整且未进入任何目标项目需求提交。

清理细节按需读取 `workflow/references/worktrees.md` 和 `workflow/references/artifact-retention.md`。
