---
name: workflow-stage-s3
description: Implement an approved plan while preserving user work and repository conventions.
---

# S3 实现

执行前按需读取 `workflow/references/git-safety.md`；需要隔离工作区时再读取 `workflow/references/worktrees.md`。
同时运行 `metrics-start`，并读取 `context.required` 中本阶段启用的静态挂载技能。

## 输入

- `work/<id>/plan.md`
- `state.md` 中的批准或低风险策略依据
- 目标项目规范和相邻实现

## 动作

1. 核对工作目录、分支、基线和未提交修改。
2. 按计划最小范围实现，同步补充相称的测试。
3. 匹配周围代码的命名、注释密度和习惯，不使用全局机械规则代替判断。
4. 按项目变更文档配置，在 `feature/<id>` 上创建或更新正式变更文档；需要集中日志的项目同步追加日志。
5. 按逻辑单元提交，不 push；正式变更文档提交必须属于需求分支，不能只提交到联测分支。
6. 记录每项计划、变更文档路径与 commit 的对应关系。

## 偏离

细节调整写入日志；范围扩大、数据结构、公共 API、风险等级或影响面关系变化属于实质性偏离，返回 S2，更新方案并重新判断闸口 B。

## 输出

代码与正式变更文档提交及 `work/<id>/impl-log.md`。不得修改无关代码或丢弃无法确认归属的现有修改。

进入 S4、返回 S2 或 BLOCKED 前，按 `workflow/references/metrics.md` 完成本轮记录；进入回路时如实增加返工次数。
