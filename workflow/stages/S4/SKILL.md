---
name: workflow-stage-s4
description: Verify the implementation against project commands, acceptance criteria, diff review, and applicable rubrics.
---

# S4 验证

按需读取 `workflow/references/verification-results.md`。运行 `metrics-start`，并加载 `config/skills.md` 为 S4 启用的 `skills/security-baseline.md`；只加载当前项目启用的流程扩展。

## 输入

- 当前分支完整 diff
- `analysis.md` 的验收标准
- `plan.md` 的验证映射
- `impl-log.md`
- 当前项目验证命令

## 动作

1. 执行项目注册的检查和测试。命令含 `<需求相关包列表>` 时，根据 `plan.md` 验证映射和实际变更文件展开为精确包路径，并在 `verify.md` 记录展开后的可复跑命令。项目配置 `advisory_verification` 中的全仓命令仅作参考：可执行时如实记录，但其结果不参与 S4 完成判据。
2. 逐条核对验收标准并保存可复核证据。
3. 以评审者视角检查完整 diff、计划偏离和适用 Rubric。
4. 检查项目配置要求的正式变更文档和集中日志：路径存在、内容覆盖实际改动、包含验证与回滚信息，并记录对应提交 hash。
5. 每项只能记录 `PASS`、`FAIL`、`NOT_RUN` 或 `BLOCKED`。
6. `FAIL` 返回 S3；`BLOCKED` 停止；`NOT_RUN` 需要人工补跑或明确接受风险。

## 输出与完成判据

向 `work/<id>/verify.md` 追加当前项目和轮次的小节。除参考性检查外，全部 PASS，或所有 NOT_RUN 已有明确风险确认，才能进入 S5。

变更文档检查未通过时不得进入 S5；启用 `dual-baseline-test` 的项目还必须证明变更文档提交已被移植到本轮 test 分支。

启用了扩展的项目还必须满足扩展自己的完成判据；未启用时不得加载其详细规则。

进入 S5、因 FAIL 回 S3、BLOCKED 或取消前，按 `workflow/references/metrics.md` 完成本轮记录；FAIL 回修计入下一轮返工。
