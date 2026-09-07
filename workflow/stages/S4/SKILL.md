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

1. 执行项目注册的必需检查和测试。占位命令按 `plan.md` 与实际 diff 展开为精确文件、包或测试过滤条件，在 `verify.md` 保存可复跑命令；PHP 至少覆盖变更文件语法与对应定向测试，测试入口须先确认确能执行这些断言。项目配置 `advisory_verification` 中的全仓命令仅作参考，其结果不参与 S4 完成判据。
2. 逐条核对验收标准并保存可复核证据。对 S1/S2 的真实合同样例和原失败 payload，回归结构、ID 关联、嵌套类型、数据粒度及异常/测试输出边界；未获得真实样例或未在目标环境执行的项继续保留缺口，不用源码合同 PASS 覆盖真实联测 NOT_RUN。
3. 以评审者视角检查完整 diff、计划偏离和适用 Rubric。
4. 检查项目配置要求的正式变更文档和集中日志：路径存在、内容覆盖实际改动、包含验证与回滚信息，并记录对应提交 hash。
5. 每项只能记录 `PASS`、`FAIL`、`NOT_RUN` 或 `BLOCKED`。
6. 需求实现验证 `FAIL` 返回 S3，并将已有 `delivery.md` 标为 `- 交付状态: STALE`、旧补丁移入 `delivery/history/`；`BLOCKED` 停止当前项目。必需项 `NOT_RUN` 需要补跑或适用范围内已有/新增的明确风险接受；参考项不制造流转阻塞。环境原因与实现失败分开记录，不把环境故障自动计为代码回修。

已知环境限制按 `workflow/references/verification-environment.md` 引用已有项目/版本/基线/影响面证据。只有该上下文改变或原结论不足以覆盖当前验证时复查；不反复尝试 Windows、WSL、Docker 或已知无法完成的全仓命令。历史 FAIL 保持原样；本轮未运行写 `NOT_RUN` 并链接原原因，不能写 PASS。

修复后根据实际影响面更新验证矩阵并重跑受影响的必需项；基线、代码、环境或验收合同改变使旧证据失效的项也需重跑。稳定环境限制和未受影响的有效证据可以引用，扩大到全仓检查需有具体理由，不能仅因阶段重新进入而重复。

验证创建临时目录、测试分支或可再生文件时，立即在 `state.md` 的资源当前清单登记精确位置、生成命令/前后状态、归属和清理授权；不能到 S6 再仅凭 ignored 名称判断来源。

## 输出与完成判据

向 `work/<id>/verify.md` 追加当前项目和轮次的小节。除参考性检查外，全部 PASS，或所有 NOT_RUN 已有明确风险确认，才能进入 S5。

变更文档检查未通过时不得进入 S5；启用 `dual-baseline-test` 的项目还必须证明变更文档提交已被移植到本轮 test 分支。

启用了扩展的项目还必须满足扩展自己的完成判据；未启用时不得加载其详细规则。

进入 S5、因 FAIL 回 S3、BLOCKED 或取消前，按 `workflow/references/metrics.md` 完成本轮记录；FAIL 回修计入下一轮返工。
