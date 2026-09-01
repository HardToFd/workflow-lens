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
2. 有权限时 push 并创建 MR/PR；无权限时生成 patch、文件清单和可直接使用的 MR/PR 描述。
3. 提供需求摘要、实现摘要、验证证据、评审重点、部署和回滚注意。
4. 在交付说明中列出正式变更文档路径、集中日志路径（如有）及其验证结论。
5. 跨项目需求明确合并顺序。

## 闸口 C

交付后等待合并或无 MR 验收。评审意见编号记录后返回 S3，修复并重新验证。

## 输出

`work/<id>/delivery.md` 和远端 MR/PR 或降级交付包。

进入 S6、因 Gate C 意见回 S3、BLOCKED 或取消前完成 `metrics.md` 本轮记录；评审回流按 L2 计入返工。
