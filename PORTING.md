# 移植指南(把本文件夹变成你的工作区)

工作流核心只依赖 Python 标准库。移植 = 拷贝 + 注册项目 + 核对技能挂载 + 试跑。Codex 与 OMP 环境可从本机 session JSONL 自动采集精确 Token；OMP 数据目录可由 `PI_CODING_AGENT_DIR` 覆盖，其他 Agent 平台不受影响，可显式传值或保留 `NOT_AVAILABLE`。

## 一、拷贝

把 `ai-dev-workflow/` 的**全部内容**(含隐藏的 `.claude/`)拷到你的工作区根目录。两种布局都支持:

- **多仓工作区**(推荐):工作区是个壳目录,目标项目作为子目录放进来(各自保留独立 .git)。在工作区 `.gitignore` 中排除这些子目录。
- **单仓内嵌**:直接拷进目标仓库根目录,`config/projects.md` 里路径写 `./`。**`work/` 默认加入该仓库 `.gitignore` 不提交**(过程产物不混入目标仓库历史,与 `workflow/artifacts.md` 归属规则一致);**仅当项目注册项声明 `过程产物入库: 允许` 时**才作为例外提交。多仓工作区则相反:`work/` 应提交(它在工作流本体仓库,不在目标仓库内)。

## 二、必改(2 个文件)

1. **`config/projects/index.json` + `config/projects/<name>.json`**:删除 example-api 示例，登记轻量判定信号和项目详情。也可继续只维护兼容入口 `config/projects.md`，但不要让两套配置表达不同事实。
2. **`skills/security-baseline.md`**:按你的技术栈补充"侧重"小节(通用部分已可用)，并确认它在 `config/skills.md` 的 S4 挂载行保持启用。

Archify 与 Diagram Design 默认停用；仅在跨项目、复杂异步链路或人类明确要求分享图时按需启用。适配器包含当前机器的绝对入口路径，换机器后如需使用，应在 GUI“设置 → 技能挂载”中重新检测并加入编排，不能照搬失效路径。

## 三、按需改(可全部保持默认)

| 文件 | 什么时候改 |
|------|-----------|
| `workflow/loops.md` | 想调回修轮次上限(默认3)、熔断条件 |
| `workflow/extensions/dual-baseline-test.md` | 你的项目有 dev/master 双基线流程(master 拉分支开发、dev 联测、交付回 master)→ 在 projects.md 注册项声明 `流程扩展: dual-baseline-test` 启用;没有此流程则无视,不声明即不生效 |
| `config/skills.md` 挂载契约 | 想调整各环节允许挂载的技能类型、挂载点、触发条件、顺序或启停状态 |
| `prds/TEMPLATE.md` | 想加团队自己的 PRD 字段(不可删验收标准) |
| `config/skills.md` + `skills/` | 有现成领域经验想预置成技能，或要接入外部 Agent Skill 适配器 |
| `workflow/manifest.json`、阶段 Skills、`protocol.md` | 调整状态、风险、闸口或阶段行为时必须保持机器清单、当前阶段 Skill 和兼容参考一致 |

## 四、平台适配(可选)

- **本地 GUI**:有 Python 3.8+ 时运行 `python gui/desktop.py --workspace .`;Windows 下可用 `powershell -ExecutionPolicy Bypass -File gui/build.ps1` 构建原生窗口版 `dist\WorkflowDesk.exe`(构建需 PyInstaller,运行无需 Python且不打开浏览器)。可将单文件程序放在别处，再运行 `& "D:\tools\WorkflowDesk.exe" --workspace "D:\path\to\workflow"` 管理指定工作区；目标目录须包含 `AGENTS.md`、`prds/`、`work/` 和 `config/`。项目可在“设置 → 项目设置”中从工作区内已有 Git 仓库导入；程序只注册路径和预填配置，不复制或克隆仓库
- **技能检测**:原生版按需只读检查工作区和当前用户目录中的固定根：`skills/*.md`、`.codex/skills`、`.claude/skills`、旧式 `.claude/commands`、`.cursor/skills`、`.gemini/skills`、`.github/skills`、`~/.copilot/skills`、`.windsurf/skills`、`~/.codeium/windsurf/skills` 和 `.agents/skills`；Windsurf 企业部署还可使用 `C:\ProgramData\Windsurf\skills`
- **检测边界**:“发现”不等于 Agent 当前已启用；只有 `config/skills.md` 中状态为“启用”的挂载行才会进入阶段上下文。外部技能只读，须在 GUI 点击“加入编排”生成当前工作区的默认停用适配器，再选择 S1～S6、触发条件、顺序并显式启用。“重新检测”不安装或执行技能，也不扫描凭据、历史、会话、临时目录或整块磁盘
- **刷新边界**:需求列表每 3 秒比较摘要，有变化才刷新；技能检测仅在打开设置或点击“重新检测”时进行。两者均不新增第三方依赖、文件 watcher 或后台服务
- **Claude Code**:`CLAUDE.md` 和 `.claude/commands/` 已就位,开箱即用
- **Cursor**:新建 `.cursorrules`,内容一行:"读 AGENTS.md 并按其自引导"
- **Codex CLI / 其他**:多数原生识别 `AGENTS.md`,无需动作
- **网页版对话**(无文件访问):开场把 AGENTS.md + 相关文档粘给它,按 capabilities.md 档位3运行
- 纪律:适配文件只能是指向 AGENTS.md 的薄壳,不得承载协议逻辑

技能目录环境覆盖：

| 产品 | 默认用户级位置 | 环境覆盖 |
|------|----------------|----------|
| Gemini CLI | `~/.gemini/skills`、`~/.gemini/extensions` | `GEMINI_CLI_HOME` 改写用户主目录基准，程序读取 `<值>/.gemini/...` |
| GitHub Copilot CLI | `~/.copilot/skills`、`~/.copilot/installed-plugins` | `COPILOT_HOME` 直接替换 `~/.copilot`；`COPILOT_SKILLS_DIRS` 可提供逗号分隔的绝对技能根 |
| Windsurf/Cascade | `~/.codeium/windsurf/skills` | Windows 企业技能根使用 `%PROGRAMDATA%\Windsurf\skills` |

Claude Code 的版本化 Marketplace 缓存会保留旧副本，静态设置不能可靠定位当前物理版本，因此程序不扫描该缓存；Cursor 只检查公开的 `~/.cursor/plugins/local`；Gemini 扩展必须含 `gemini-extension.json`；Copilot 插件只检查 `installed-plugins` 官方布局及白名单 manifest。目录、manifest 或设置不足以证明启用时，统一显示“已发现未确认”或诊断，不猜测状态。

## 五、试跑验证

1. 写一个小而真的 PRD 放进 `prds/`(改文案、加个小字段级别)
2. 对代理说"读 AGENTS.md,执行需求 <id>"
3. 核对:每阶段启用技能是否进入 `context.required` → S1 影响面是否落到文件路径 → S2 的方案与验证映射是否完整 → 闸口B 是否真的停下等你 → S4 是否真跑了项目验证 → `metrics.md` 是否逐阶段记录 → S5 交付物是否含部署注意；仅在按需生成影响面图时追加核对图与方案是否一致
4. 跑完一轮后按体验微调(环节粒度、技能内容),再上真实需求
5. 运行 `python workflow/workflowctl.py doctor`，确认入口和阶段上下文没有超过预算

## 文件清单(移植完整性自查)

```
AGENTS.md                    通用入口(协议自引导)
README.md / PORTING.md       人类文档
EVALUATION.md                当前静态评估(非运行协议)
CLAUDE.md  .claude/commands/ Claude Code 薄壳(prd-run 主入口)
gui/        server.py desktop.py build.ps1 index.html          本地 GUI与Windows单文件构建
workflow/  manifest.json core.py workflowctl.py          机器定义、静态技能挂载、度量与上下文路由
workflow/stages/S1..S6/SKILL.md                           按阶段加载的执行说明
workflow/references/                                     Git、闸口、验证等按需参考
workflow/  protocol.md stages.md loops.md artifacts.md   兼容性深层参考
workflow/extensions/  dual-baseline-test.md              流程扩展(按需启用)
config/projects/index.json + <name>.json                 渐进式项目配置
config/    capabilities.md projects.md skills.md         兼容配置层
skills/    security-baseline.md + imported-*.md          预置技能与外部适配器(3)
prds/      TEMPLATE.md                                   PRD 模板
work/      .gitkeep                                      过程产物区(空)
```
