# AI 开发工作流(平台无关 · PRD → 交付)

一套**不绑定任何模型/平台**的 AI 开发工作流:PRD 接入后,AI 代理完成 解析→方案→编码→自测→交付,人只在风险和交付边界介入。工作流由 Markdown 任务产物、JSON 机器清单和无依赖 Python 路由器组成；无法运行 Python 时仍可按阶段 Skill 由人工中继。

当前版本采用**渐进式上下文加载**：`AGENTS.md` 只负责路由，`workflow/manifest.json` 提供机器定义，`workflow/workflowctl.py context <id>` 只返回当前阶段需要读取的阶段 Skill、静态挂载技能、项目配置和任务产物。旧版 Markdown 状态与配置继续兼容。

> 初次使用:先按 `PORTING.md` 完成移植三步(注册项目→过一遍配置→试跑)。

## 架构:一条主线 + 五个可插拔面

```
   运行环境配置 ─── config/capabilities.md   能力自检/降级(换平台看这里,不算扩展面)

                    ┌─ config/projects.md       项目注册(加仓库改这里)
                    ├─ config/skills.md         技能静态挂载(改表生效)
   五个可插拔面 ────┼─ workflow/extensions/     流程扩展(环节内插子步骤,按项目启用)
                    ├─ workflow/loops.md        循环策略(调阈值改这里)
                    └─ workflow/artifacts.md    产物模板(可增字段,不可删必填)
                              │ 注入
   路由层(稳定) ── workflow/manifest.json ─ workflowctl.py ─ stages/Sx/SKILL.md
                              │
   深层参考 ───────── workflow/protocol.md / references/（仅遇到相应边界时加载）
                              │ 运行于
   状态层 ────────── prds/(输入) + work/<id>/(进度与产物) + 目标仓库需求分支(代码)
```

> 五个可插拔面 = protocol §6 的权威清单:projects / skills / extensions / loops / artifacts。`capabilities` 是运行环境配置,单独一层,不计入五面。

**主线(S1→S6)**:

```
PRD 入 prds/
  → S1 解析与影响面     ──有阻塞歧义──→ 【闸口A·按需】人答选择题
  → S2 技术方案          ──────────────→ 【闸口B·必经·需求级】人批 10 行摘要
       └ 影响面图仅在跨项目、复杂异步链路或明确要求分享时按需生成，不阻塞闸口
  → S3 实现(注册分支模型定义的需求分支,只commit)
  → S4 验证 ⇄ S3 回修(≤3轮,超限升级人工)
        └ 部分项目在 S4 内含 dev 联测子步骤(见 workflow/extensions/,不是独立阶段)
  → S5 交付(push + MR)──────────────→ 【闸口C·必经·项目级】人审MR,意见回流S3
  → S6 归档 + 经验沉淀为技能候选
```

## 文档地图(读什么,按角色)

| 你是 | 读 |
|------|-----|
| **AI 代理**(任何平台) | `AGENTS.md` → `metrics-start <id>` → `workflowctl context <id>` → 当前阶段 Skill + 静态挂载技能 |
| **人类使用者** | 本文件 + `prds/TEMPLATE.md`(怎么写 PRD)即可上手 |
| **移植者** | `PORTING.md` |
| **要改流程的人** | `workflow/manifest.json` + 对应阶段 Skill；边界细节按需读 `workflow/protocol.md` |
| **要接新项目的人** | `config/projects.md`(加一个注册项) |
| **要加领域经验的人** | `config/skills.md`(技能格式与挂载协议) |

## 快速开始

1. 把 PRD 写成 `prds/<id>.md`(模板 `prds/TEMPLATE.md`,核心是可核对的验收标准)
2. 对任何 AI 代理说:**"读 AGENTS.md,执行需求 `<id>`"**；代理会通过 `workflowctl context` 按需加载阶段说明和已启用技能
3. 在闸口 A/B/C 回复它;其余时间等交付

### 本地 GUI（可选）

Windows 下可构建单文件桌面程序（构建时需安装 PyInstaller，运行时无需 Python）：

```powershell
powershell -ExecutionPolicy Bypass -File gui/build.ps1
```

双击 `dist\WorkflowDesk.exe` 即可；程序使用系统原生桌面控件，内容直接显示在应用窗口内，不打开浏览器。

若把单文件程序放在工作区之外，显式指定工作流根目录：

```powershell
& "D:\tools\WorkflowDesk.exe" --workspace "D:\path\to\workflow"
```

该目录须包含 `AGENTS.md`、`prds/`、`work/` 和 `config/`。用 Python 启动原生窗口时同样支持：

```powershell
python gui/desktop.py --workspace .
```

需要浏览器版操作台时才运行：

```bash
python gui/server.py --workspace .
```

打开 `http://127.0.0.1:8765/`。GUI 可查看需求、状态和阶段产物，创建 PRD，写入当前正在等待的闸口答复，并显示只读 Git 状态。

原生版“设置 → 技能挂载”只检测公开的固定目录：工作区原生 `skills/*.md`，Codex 的 `.codex/skills`，Claude Code 的 `.claude/skills` 和旧式 `.claude/commands`，Cursor 的 `.cursor/skills`，Gemini CLI 的 `.gemini/skills`，GitHub Copilot 的 `.github/skills`/`~/.copilot/skills`，Windsurf/Cascade 的 `.windsurf/skills`/`~/.codeium/windsurf/skills`，以及通用 `.agents/skills`；工作区级和用户级目录存在时分别检测。已安装插件或扩展只通过公开的本地根和白名单配置/manifest 补充，不猜测 Marketplace 临时缓存。

“发现”不代表某个 Agent 当前已启用该技能，界面会把来源状态、编排状态、来源类型和启用证据分开显示。外部目录始终只读；用户点击“加入编排”后，程序才在当前工作区创建默认停用的适配器，再显式配置 S1～S6 挂载点、触发条件和顺序。“重新检测”按需重扫，不使用 watcher、后台扫描或新依赖。环境覆盖和各平台用户级路径见 `PORTING.md`。

需求摘要每 3 秒差量检查一次；无变化不重绘，变化时保留搜索、当前需求和产物。单个损坏或不可读的 PRD/状态文件显示“读取失败”，不阻断其他需求更新。“设置 → 项目设置 → 导入项目”可注册工作区内已有的 Git 仓库并预填规范文件和安全检查命令；分支模型必须人工填写精确基线后才能保存。能力档位显示完整执行边界。Markdown 仍是唯一真相源；GUI 不启动 AI 代理，也不执行任意 shell 命令。运行自测：`python gui/server.py --self-test --workspace .`。

多需求并行:过程产物按 `work/<id>/` 隔离;具备 Shell/Git 且仓库有可用基线时,每个需求进入 S3 前默认使用独立 worktree;无能力或无基线且存在同仓冲突时安全 BLOCKED。会话中断/换模型:新代理读 `work/<id>/state.md` 无损接管。

## 扩展机制速览

| 扩展需求 | 做法 | 改动范围 |
|----------|------|----------|
| 换模型/换平台 | 无需任何改动,新代理读 AGENTS.md(运行环境自检见 capabilities.md) | 0 文件 |
| 新目标仓库 | `config/projects/index.json` 加索引并新增项目详情 | 2 文件 |
| 加/卸领域技能 | `skills/` 放文件或生成外部适配器 + `config/skills.md` 挂载表改一行 | 2 文件 |
| 环节内插子步骤(如 dev/master 双基线联测) | workflow/extensions/ 放扩展 + projects.md 注册项声明启用 | 2 文件 |
| 调回修轮次等策略 | loops.md 改数字 | 1 文件 |
| 产物增字段 | artifacts.md 加列(不可删必填字段) | 1 文件 |
| 平台快捷方式(斜杠命令等) | 允许,但只能是"指向 AGENTS.md 的薄壳" | 见 capabilities.md 适配层规则 |

## 工作流诊断

```powershell
python workflow/workflowctl.py doctor
python -m unittest workflow.test_workflowctl
python gui/server.py --self-test --workspace .
```

第一条检查入口和阶段上下文预算、机器清单及项目配置；第二条验证共享核心与旧状态兼容；第三条验证 GUI。

每个阶段先运行 `metrics-start`，退出前运行 `metrics-record`；开始和结束时间统一显示为 UTC+8（ISO 8601 `+08:00`）。有效 Codex session id 优先从 `token_count.info.last_token_usage` 采集精确增量并去重；OMP 环境从当前主 session 及其嵌套 agent 的 assistant `usage` / `model_usage` 按阶段窗口汇总。其他环境仍可显式传值，无法核验时写 `NOT_AVAILABLE`。`metrics.md` 与按需生成的影响面图均为过程产物，不得加入任何目标项目的需求 commit 或 MR/PR。
