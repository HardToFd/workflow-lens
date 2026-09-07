---
name: workflow-stage-s1
description: Parse a PRD, select target projects, map acceptance criteria, and identify blocking ambiguity.
---

# S1 解析与影响面分析

只处理需求理解和只读调研，不修改目标仓库。

开始前运行 `metrics-start`，并读取 `context.required` 中本阶段启用的静态挂载技能。

## 输入

- `prds/<id>.md`
- 存在 `config/projects/index.json` 时以该索引和选中项目 JSON 为权威；仅没有索引时读取兼容入口 `config/projects.md`
- 已有 `work/<id>/state.md`（恢复时）

## 动作

1. 复述需求目标与明确不做的范围。
2. 根据判定信号选择一个或多个目标项目。
3. 只读调研代码，将影响面定位到文件或符号。
4. 为每条验收标准定义可执行或可观察的验证方式。
5. 区分阻塞性歧义与可以明确标注的合理假设。
6. 根据 `workflow/manifest.json` 评估风险等级 R0～R3。

涉及接口、跨项目字段或存储时，在现有影响面/验收表中补最小合同证据：脱敏真实请求与完整响应样例的来源、日期和环境；ID 来源及关联关系；返回结构前后差异；嵌套字段的 number/string/null/缺失类型；一行或一个消息代表的数据粒度。涉及存储的连接别名、数据库/schema、读写点和测试输出边界分别核对，不能由表名或同名字段推断。只在已有权限内取证，不转储连接凭据。

样例不可得时标记 `CONTRACT_GAP`、缺少内容及对应验收项；合成样例注明合成，不冒充真实媒体/数据验证。只有缺口会导致不同实现且无法作有依据的选择时进入 Gate A；其他缺口随 S2/S4 验证映射继续传递。原失败 payload 脱敏后应保留字段类型、层级和 ID 等价关系，供定向回归复用。

复用既有验证环境证据时按需读 `workflow/references/verification-environment.md`，记录项目、运行时版本、基线和影响面；不因新需求再次启动就重复排查相同环境限制。

## 输出与完成判据

写 `work/<id>/analysis.md`，包含：摘要、功能点、目标项目、验收标准与验证方式、影响面、数据变化、风险等级、假设和阻塞性歧义。

影响面达到文件级、验收标准均有验证方式且目标项目明确后完成。存在阻塞性歧义时进入闸口 A。

离开本轮 S1 前按 `workflow/references/metrics.md` 写入 token、返工、效率比和墙钟用时；即使 BLOCKED 或取消也要留记录。
