# AI 开发工作流入口

本工作区使用按阶段加载的 PRD→交付工作流。不要在启动时读取整个 `workflow/` 或全部配置。

## 开始或恢复需求

1. 从用户输入取得需求 id；不存在时请用户提供。
2. 运行 `python workflow/workflowctl.py validate-id <id>`。
3. 运行 `python workflow/workflowctl.py context <id>`，先确认目标项目、阶段及 `runnable`。跨项目可用 `--project <注册名>` 指定目标；全部阻塞或等待时不开始新计时。
4. 对可执行目标运行 `python workflow/workflowctl.py metrics-start <id>`；指定项目时与 context 使用相同 `--project`，开始本阶段计时。
5. 只读取命令返回的 `required` 文件；其中包含 `config/skills.md` 静态挂载表里对本阶段启用的技能。
   同时检查 `delivery.status`：`STALE` 的旧交付物不得复用；`UNVERIFIED` 表示旧材料尚未登记内容快照，不代表验证失败或需要恢复已归档需求。
6. 执行当前阶段 `SKILL.md`；只有遇到相应动作时才读取 `references_on_demand`。
7. 阶段完成、失败、阻塞、取消或进入回路前，运行 `metrics-record` 把 token、区间用时和有证据的等待秒数写入唯一的 `work/<id>/metrics.md`，再更新 `state.md`；回流用 `rework-record` 登记唯一事件（口径见当前阶段加载的 metrics 参考）。Codex 与 OMP 自动采集精确 token，缺失写 `NOT_AVAILABLE`；旧返工数字/单元比不作质量汇总，下一轮从第 2 步开始。

没有 shell 时，人工按同样顺序提供文件内容；`workflow/manifest.json` 是状态、风险、闸口和路由的机器权威定义。

`config/skills.md` 是技能静态挂载表；技能选择只由仓库内表格的挂载点、状态和行序决定，不调用外部运行时检索、打分或路由。S2 默认以 `analysis.md` 的影响面表和 `plan.md` 的审批摘要完成方案审批；影响面分享图仅在跨项目、复杂异步链路或人类明确要求分享时按需生成，且不阻塞 Gate B。

## 始终生效

- 不得丢弃、覆盖或隐藏无法确认属于当前需求的用户修改。
- 验证必须如实记录；不得删测试、放宽标准或把 `NOT_RUN` 写成 `PASS`。
- 只做需求范围内的改动；实质性扩大范围必须重新取得方案批准。
- 生产操作和不可逆数据操作不由本工作流自动执行。

## 人工边界

- 阻塞性歧义进入闸口 A。
- R2/R3 方案必须经过闸口 B；R0/R1 只有项目配置明确允许时才能跳过。
- 合并或无 MR 验收必须经过闸口 C。

运行 `python workflow/workflowctl.py doctor` 可检查路由文件、上下文预算和结构完整性。
