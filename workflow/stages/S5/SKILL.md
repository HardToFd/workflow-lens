---
name: workflow-stage-s5
description: Deliver a verified branch or patch with review-ready evidence.
---

# S5 交付

开始前运行 `metrics-start` 并读取本阶段启用的静态挂载技能；过程度量不得随目标项目 push 或写入 MR/PR 描述。

## 输入

- 满足完成判据的 `work/<id>/verify.md`
- 当前项目交付目标和远端能力

## 动作

1. 核对分支、HEAD、工作区和预期提交集合。
2. 先按当前方案、HEAD 与本轮验证生成文件清单、MR/PR 描述及需要的 patch；旧交付物按原字节保留到历史目录，当前摘要不得混入失效合同。
3. 提供需求摘要、实现摘要、验证证据、评审重点、部署和回滚注意。
4. 在交付说明中列出正式变更文档路径、集中日志路径（如有）及其验证结论。
5. 跨项目需求明确合并顺序。
6. 核对当前交付与 `plan.md`、`impl-log.md`、`verify.md` 一致后，在 `delivery.md` 顶部写 `- 交付状态: CURRENT`，执行 `python workflow/workflowctl.py delivery-record <id>` 登记当前内容快照。
7. push、创建 MR/PR、发送补丁或进入 Gate C 前执行 `python workflow/workflowctl.py delivery-check <id>`，必须为 CURRENT；有权限时按已授权范围交付。STALE 须重新核对和生成，UNVERIFIED 须先核对现有材料再登记，不得用重复登记代替真实复核。

## 闸口 C

交付后等待合并或无 MR 验收。评审意见编号记录后返回 S3，旧交付标记 STALE，修复并重新验证。CURRENT 只表示内容与登记时一致，不代表测试通过、部署或人工验收；闸口 C 仍须按原授权规则确认。

## 输出

`work/<id>/delivery.md` 和远端 MR/PR 或降级交付包。

进入 S6、因 Gate C 意见回 S3、BLOCKED 或取消前完成 `metrics.md` 本轮记录；评审回流按 L2 计入返工。
