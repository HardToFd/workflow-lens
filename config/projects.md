# 目标项目注册表(新增项目=加一节,主线零改动)

S1 用"判定信号"选目标项目;S3 遵守"规范文件";S4 执行"验证命令"。每个注册项就是一份项目接入合同。

> 新版优先使用 `config/projects/index.json` 作为轻量判定索引，并在选中项目后读取 `config/projects/<name>.json`。本文件继续作为无 JSON 配置时的兼容入口，不要求代理同时读取两套配置。

> **移植后第一件事**:删除下方示例,按模板注册你自己的项目。至少注册一个,否则 S1 无法判定目标。

**配置完整性检查(S1/S2 执行)**:注册项启用内置 `dual-baseline-test` 时,必须同时声明“联测方式”,且分支模型必须使用 `origin/master`、`origin/dev`、`feature/<需求id>`、`test/<需求id>` 这组固定契约;任一缺失或不匹配都标记为**阻塞性配置问题**(BLOCKED),不得进入 S3。其他命名须先修改该扩展,不能带着不兼容配置运行。

## 注册项模板

```markdown
## <注册名>
- 路径: <工作区内相对路径>(若为独立git仓库,git操作须在该目录内执行)
- 技术栈: <语言/框架/存储>
- 判定信号: <什么样的需求归它——S1 依据此判定>
- 规范文件: <S3 编码前必读的仓内规范清单;没有则写"无,遵循既有代码风格">
- 验证命令: <S4 逐条执行的检查/测试命令,标注哪些可能缺环境>
- 参考性验证: <不阻塞流转的全仓检查;没有则写"无">
- 正式变更文档: <目标仓库中的需求文档路径和集中变更日志;过程产物不能代替它>
- 分支模型: <开发基线、含需求id的需求分支命名、MR/PR交付目标,如“从 origin/main 拉 feature/<需求id>,MR 合入 main”>
- 远端: <MR/PR平台;无权限时的降级方式>
- 流程扩展: <无 | workflow/extensions/ 下的扩展名,如 dual-baseline-test>
- 联测方式: <条件必填,仅当流程扩展含 dual-baseline-test 时> test 分支如何部署、谁执行、验证命令或步骤、无权限时如何降级
- 过程产物入库: 禁止 | 允许    # 默认禁止;仅单仓内嵌且需审计留痕时设"允许",语义见 workflow/artifacts.md 归属规则
- 审批策略: <R0/R1/R2/R3 分别为 auto 或 gate_b;R2/R3 不得配置 auto>
```

---

## example-api(示例,移植后删除)

- 路径: `example-api/`
- 技术栈: TypeScript / Node.js / PostgreSQL
- 判定信号: 后端接口、数据模型、定时任务类需求
- 规范文件: `CONTRIBUTING.md`、`docs/api-style.md`
- 验证命令:
  1. `npm run lint`
  2. `npm run typecheck`
  3. `npm test`
- 参考性验证: 无
- 正式变更文档: `docs/changes/<需求id>.md`，并更新 `docs/CHANGELOG.md`
- 分支模型: 从 `origin/main` 拉 `feature/<需求id>`,PR 合入 `main`
- 远端: GitHub,用 `gh pr create`;无 CLI 时降级为推送分支+PR描述文本
- 流程扩展: 无
- 过程产物入库: 禁止
- 审批策略: R0=`auto`，R1/R2/R3=`gate_b`

## 跨项目需求约定

多项目共同完成一个需求时:S2 必须拆为有依赖顺序的独立子任务(各自分支/MR),delivery.md 写明合并顺序。<在此补充你的系统间数据流向约定,例如"先后端产数、后前端展示">
