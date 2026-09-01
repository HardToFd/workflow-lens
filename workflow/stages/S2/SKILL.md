---
name: workflow-stage-s2
description: Turn an approved analysis into a minimal, reviewable implementation plan.
---

# S2 技术方案

开始前运行 `metrics-start`。默认用 `analysis.md` 的影响面表和 `plan.md` 的审批摘要推进 Gate B，不等待流程图。

## 输入

- `work/<id>/analysis.md`
- `work/<id>/questions.md`（发生过闸口 A 时）
- 已选目标项目的规范和高保真参考

## 动作

1. 将影响面转成文件级改动清单，每项引用仓内现有参照。
2. 将每条验收标准映射到验证动作和通过判据。
3. 单列数据、公共 API、权限、安全和跨项目变化。
4. 明确依赖顺序、风险、回滚方式和不做事项。
5. 确认或修正 S1 风险等级。
6. 读取目标项目的变更文档配置，在 `plan.md` 改动清单中明确正式变更文档路径；项目配置要求集中日志时，同时列出需要追加的日志文件。
7. 仅当需求跨项目、存在复杂异步链路，或人类明确要求分享图时，按需读取 `workflow/references/impact-visualization.md`；图是辅助材料，不阻塞方案审批。

## 闸口

按 `workflow/references/gates.md` 判断是否需要闸口 B。R2/R3 必须审批；R0/R1 只有在项目配置明确允许时才能跳过，并在 `state.md` 留下策略依据。

## 输出与完成判据

写 `work/<id>/plan.md`：十行内摘要、风险等级、改动清单、变更文档路径、验证映射、风险与回滚、明确不做和修订记录；按需生成影响面图时再附图与审查链接。

每项改动有参照、每条验收标准有验证动作后即可完成；影响面图及其审查不参与 S2 或 Gate B 的完成判定。离开本轮 S2 或 Gate B 打回前记录 `metrics.md`；打回计入下一轮返工。
