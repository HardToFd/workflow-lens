---
name: workflow-stage-s6
description: Close an accepted delivery, clean workflow-owned temporary resources, and retain useful evidence.
---

# S6 完成归档

仅当所有目标项目都已合并或已完成无 MR 验收时执行。
开始前运行 `metrics-start` 并读取本阶段启用的静态挂载技能。

## 动作

1. 将所有项目行和顶层状态标记完成。
2. 仅清理明确标记为本工作流创建、且经核验安全的临时资源。
3. 保留任务产物，记录无法自动清理的项目供人工处理。
4. 只有经过验证、预计会在后续同类需求复用的经验才写入技能候选；一次性事实留在任务产物。候选由人类审阅后移入 `skills/` 并登记到 `config/skills.md`，不会自动挂载。
5. 汇总并完成 S6 的 `metrics.md` 记录，确认 S1～S6 每个实际进入过的环节都有一条记录；Codex/OMP 自动采集或历史回填仍无法取得精确 token 时明确保留 `NOT_AVAILABLE`。

## 输出与完成判据

- `state.md` 顶层和项目行均完成。
- 临时分支与 worktree 均明确为已清理或待人工。
- `work/<id>/` 保留作为审计与接管依据。
- `metrics.md` 完整且未进入任何目标项目需求提交。

清理细节按需读取 `workflow/references/worktrees.md` 和 `workflow/references/artifact-retention.md`。
