---
name: workflow-stage-s1
description: Parse a PRD, select target projects, map acceptance criteria, and identify blocking ambiguity.
---

# S1 解析与影响面分析

只处理需求理解和只读调研，不修改目标仓库。

开始前运行 `metrics-start`，并读取 `context.required` 中本阶段启用的静态挂载技能。

## 输入

- `prds/<id>.md`
- `config/projects.md`；项目很多时优先读取 `config/projects/index.json`，选中后再读项目详情
- 已有 `work/<id>/state.md`（恢复时）

## 动作

1. 复述需求目标与明确不做的范围。
2. 根据判定信号选择一个或多个目标项目。
3. 只读调研代码，将影响面定位到文件或符号。
4. 为每条验收标准定义可执行或可观察的验证方式。
5. 区分阻塞性歧义与可以明确标注的合理假设。
6. 根据 `workflow/manifest.json` 评估风险等级 R0～R3。

## 输出与完成判据

写 `work/<id>/analysis.md`，包含：摘要、功能点、目标项目、验收标准与验证方式、影响面、数据变化、风险等级、假设和阻塞性歧义。

影响面达到文件级、验收标准均有验证方式且目标项目明确后完成。存在阻塞性歧义时进入闸口 A。

离开本轮 S1 前按 `workflow/references/metrics.md` 写入 token、返工、效率比和墙钟用时；即使 BLOCKED 或取消也要留记录。
