# 当前评估

- 评估日期：2026-09-01
- 评估范围：渐进式上下文路由、阶段 Skills、结构化项目配置、静态技能挂载、阶段度量、管理 GUI 与 Workflow Lens
- 结论：结构检查、共享核心测试、两个 GUI 自测和只读接口验证通过；真实目标项目的完整 PRD→S6 仍需使用者在自己的环境中验证

## 本轮可复核结果

```powershell
python workflow/workflowctl.py doctor
python -m unittest workflow.test_workflowctl
python gui/server.py --self-test --workspace .
python gui/dashboard_server.py --self-test --workspace .
node --check gui/dashboard/app.js
python -m compileall -q workflow gui
git diff --check
```

结果：

- `workflowctl doctor`：通过，入口、6 个阶段 Skill、引用文件和结构化项目配置完整。
- 共享核心测试：8 项通过，覆盖 ID、状态转移、渐进加载、静态技能挂载和阶段度量。
- 管理 GUI 自测：通过，覆盖 ID、创建、解析、路径保护、闸口、设置、项目导入、原子写入和工作区场景。
- Workflow Lens 自测：资源和工作区数据入口通过；只读服务首页返回 200，写请求返回 405。
- Python 编译检查和 Git 空白检查：通过。
- `workflowctl doctor` 对入口、六阶段 Skill、必需策略、通用示例项目和指标采集器均无错误或警告。

## 本轮架构变化

1. `workflow/manifest.json` 成为阶段、转移、风险、闸口和 ID 的机器定义。
2. `workflow/core.py` 向 CLI 和 GUI 提供共享阶段、闸口与 ID 校验。
3. `workflow/workflowctl.py context <id>` 按任务状态返回当前阶段所需文件。
4. S1～S6 拆为独立 `SKILL.md`，Git、安全、验证和清理规则按需引用。
5. 项目配置支持轻量 `index.json`，选中项目后再加载详情。
6. 旧 Markdown 状态与配置继续兼容，避免一次迁移破坏现有任务。
7. GUI 自测不再依赖 JSON 嵌套深度造成的解释器偶然行为。
8. 每次阶段尝试记录可核验的时间、Token、效率与返工；缺失值保持 `NOT_AVAILABLE`。
9. Workflow Lens 以只读方式展示并行需求时间轴、阶段画布和指标下钻。

## 剩余缺口

- 尚未用真实目标项目完整跑一条 PRD→S6。
- `state.md` 仍是当前写入格式；未来若迁移到 `state.json`，必须先让 GUI、CLI 和旧任务迁移工具共同使用同一原子写入实现。
- GUI 的闸口状态更新仍有部分 Markdown 表格操作代码；阶段、闸口集合和 ID 校验已共享，完整状态转换引擎仍可继续提取。
- Workflow Lens 的历史统计质量取决于各需求是否存在完整 `metrics.md`，不会用估算值填补缺口。
