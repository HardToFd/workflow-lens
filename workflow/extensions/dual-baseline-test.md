# 流程扩展: 双基线联测(master 开发 / dev 联测 / master 交付)

- 插入点: **S4 内部子步骤**(不是独立阶段,主阶段始终为 S4);清理动作是 S6 内部子步骤
- 启用方式: `config/projects.md` 注册项声明 `流程扩展: dual-baseline-test`,并满足 projects.md 的固定分支契约与“联测方式”校验
- 适用场景: dev 环境代码与 master 分叉大,master 基线的实现分支无法直接部署 dev 联测

## 分支模型

```
origin/master ──┬───────────────────────────────────→ (最终 MR 合入 ← S5,不变)
                └─ feature/<id>       ← S3 开发、S4 本地验证(始终以 origin/master 为基线)
origin/dev ─────┬───────────────────────────────────→ (只承载联测,永不合回 master)
                └─ test/<id>          ← S4 联测子步骤:从 origin/dev 拉出,cherry-pick feature/<id> 后部署
```

**铁律:代码和正式变更文档流向单向 `feature/<id> → test/<id>`。**
1. `test/<id>` 是一次性载具:联测通过即完成使命,**绝不合回** master 或 feature 分支
2. 移植用 **cherry-pick**,**禁止 merge**——merge 会把 master 基线整体带进 dev,污染 dev 环境
3. 联测中发现问题,**修复和正式变更文档更新只提交到 `feature/<id>`**(回 S3),再重新 cherry-pick;禁止直接在 test 分支修——否则修复留在 dev 侧,最终交付的 master 分支上没有

## S4 联测子步骤

前置: S4 本地验证已满足完成判据(全 PASS 或 NOT_RUN 已获确认)。联测状态记入 state.md 项目状态表"联测状态"列,起始 `NOT_STARTED`。

1. **工作树与基线核验**:先确认当前分支严格等于 `feature/<id>`、工作区干净,否则按 protocol.md 置 `BLOCKED`,不得带修改切换分支;再执行 `git fetch origin`,确保 `origin/master`、`origin/dev` 为最新(不依赖可能落后的本地 master/dev)
2. **确定提交集合**: 先执行 `git rev-list --merges origin/master..feature/<id>`;结果非空说明提交集合含 merge commit,立即置 `BLOCKED`,不得用缺少主线语义的普通 cherry-pick 猜测移植,由人整理线性历史后重试。结果为空时,取 `origin/master..feature/<id>` 的提交哈希列表,**按从旧到新排列**,记入 verify.md 本轮联测记录。根据项目 `change_tracking` 配置核对正式变更文档路径；必需文档或集中日志不在 feature 差异中时,不得进入联测,置 `FAIL` 返回 S3。
3. **建联测分支**: 首轮从 `origin/dev` 拉 `test/<id>`,创建后立即把“精确分支名 + 创建点 SHA(本轮基线 SHA) + 第 2 步提交集合”绑定记录到 verify.md,同时把精确分支名追加到“联测分支历史”,联测状态置 `RUNNING`
4. **移植提交**: 按第 2 步的顺序**逐个 cherry-pick** 上述哈希,正式变更文档及集中日志提交不得漏移植。若 Git 报某提交为空/补丁已存在,先确认无冲突且工作区 diff 为空,把该哈希与“dev 已含等价补丁”证据记入 verify.md 后执行 `git cherry-pick --skip`;无法确认则按实质冲突处理,不得盲目跳过
5. **冲突处置**(dev 与 master 分叉的必然结果):
   - 机械冲突(上下文漂移、格式)→ 代理解决,记录到 verify.md
   - **实质冲突**(同一逻辑在 dev 已被改走、依赖的接口在 dev 不存在)→ 先把失败提交哈希、冲突文件、判断依据记录到 verify.md,再走且只走以下一条路径:
     - **默认整轮回滚**:核对当前分支严格等于 state.md“联测分支”列记录的本轮精确分支名,并从 verify.md 同一轮绑定记录取得该分支的基线 SHA → `git cherry-pick --abort` 退出当前失败提交 → `git checkout -B <本轮精确联测分支名> <本轮基线SHA>` 回到本轮移植前。核对 HEAD == 本轮基线 SHA、工作区干净后,联测状态置 `BLOCKED` 请人裁决。`--abort` 不会撤销此前逐个成功移植的提交,因此回到本轮基线 SHA 的步骤不可省略
     - **保留冲突现场**:仅当人类在执行 abort 前已明确要求现场处理时,才不执行 abort/重建;立即把联测状态置 `BLOCKED`,并在 state.md 交接备注写明本轮精确分支名及“处于 cherry-pick 冲突中间态”。abort 之后不得再声称保留了冲突现场
   - **语义澄清**:feature 本就从 master 拉出,dev 特有的冲突通常**不阻止 feature 合入 master**;它表示"当前 master 实现无法直接适配 dev 联测环境,未来 master 同步到 dev、或 dev 继续承载该功能时需处理"。**是否阻塞 master 交付,由人按项目发布策略决定**,代理不得仅凭 dev 差异断言 feature 不能合入 master
   - **人工裁决后的三条合法路径**(不得让 `BLOCKED` 直接进入 S5):
     - **人决定继续解决当前冲突**:仅适用于上面“保留冲突现场”路径;按人的方案解决后执行 `git cherry-pick --continue` 并完成剩余提交,把联测状态恢复为 `RUNNING` 后继续部署联测。若解决方案包含应交付到 master 的业务修复,必须放弃 test 现场并回 S3 修改 feature,不得只留在 test 分支
     - **人决定阻塞**:联测状态保持 `BLOCKED`,等待 dev 兼容方案,S4 不完成
     - **人接受风险、允许 master 交付**:若此前保留了冲突现场,先对 state.md 记录的本轮精确联测分支执行 abort 并回到基线 SHA;确认工作区干净后,把该联测项及联测状态由 `BLOCKED` 改为 `NOT_RUN`,在 state.md "NOT_RUN 确认"记录批准日期、原话与风险说明,`git checkout feature/<id>` 切回后按既有 `NOT_RUN` 规则满足 S4 完成判据、进入 S5
6. **部署与联测**: 按注册项"联测方式"执行(部署命令/CI 触发/请人部署;无权限时降级:给出部署物与验证步骤清单,人执行后回贴结果)
7. **记录**: verify.md 追加"联测"节,联测项用四态(PASS/FAIL/NOT_RUN/BLOCKED);记录正式变更文档路径、feature 文档提交 hash、test 分支对应提交 hash 及内容一致性;同步更新 state.md 联测状态列
8. **重建 test 分支重新联测**(触发来源决定计入哪个循环):
   - **联测本身或其他 S4 验证 FAIL** 导致的重建 → 回 S3 修 `feature/<id>` 或更新正式变更文档 → 本地 S4 重验 → 重建 test 分支 → 重新联测,**计入该项目 L1 回修轮次**(见 loops.md L1,每项目上限 3)
   - **闸口C 评审回流** 导致的重建 → 只增加 delivery.md 的 **L2 评审轮次,不加 L1**;重建 test 分支这个动作本身不计任何轮次。评审修改后重新验证若真出现 `FAIL`,那次失败才按 L1 计数
   - 重建策略(避免误用强推、保证可清理):
     - **优先用新的轮次分支** `test/<id>-r2`、`-r3`…(远端不冲突,历史可追溯)
     - **每轮都重新执行第 1~4 步**:刷新 `origin/master`/`origin/dev`,重新检查 merge commit 并确定提交集合,从当前 `origin/dev` 创建本轮精确分支,再逐个 cherry-pick,包括本轮最新的正式变更文档提交;不得沿用上一轮基线 SHA 或提交集合
     - **每创建一轮,立即把“精确分支名 + 本轮基线 SHA + 本轮提交集合”绑定记录到 verify.md**,并把精确分支名追加到“联测分支历史”列表(不通配、不推导);state.md 项目状态表“联测分支”列只保留当前最新一轮的名字,历史全量在 verify.md
     - 若坚持复用同名分支且远端已存在:仅在确认远端该分支确为本需求上一轮联测分支后,用 `git push --force-with-lease`(禁止无保护的 `--force`/普通强推);每次重写在 verify.md 记录轮次与新 HEAD
9. **通过后切回并核验**:联测状态置 `PASS`,S4 完成。进入 S5 前**必须 `git checkout feature/<id>` 切回**,并核验当前分支 == `feature/<id>`、HEAD、工作区干净、提交集合符合预期、正式变更文档仍存在于 feature 分支——**交付对象永远是 feature → master 的 MR**,test 分支保留至 S6 清理,绝不作为交付分支

## S6 test 分支清理子步骤

在人类确认 master MR 合并后执行:
1. 以 **verify.md "联测分支历史"列表**为准(而非 state.md 的单值最新分支),先按精确分支名去重,再处理该需求创建过的所有 test 分支
2. 每个分支删除前核对名字**严格等于**列表中记录的精确名(不使用通配符、模糊变量或 `test/<id>` 硬编码);删本地,有远端推送过则一并删远端,无远端删除权限的**逐个**记"待人工清理"
3. 清理结果写入 delivery.md 的"联测清理结果"小节(每个分支一行:已删除/待人工)。**不要把清理状态写进 state.md "联测状态"列**——该列只允许 `NOT_STARTED/RUNNING/PASS/FAIL/NOT_RUN/BLOCKED`,清理是独立维度

## state.md 记录

**以 protocol.md §3 的权威项目状态表为准**,不复制整表。执行本扩展时只需把当前项目行的“联测分支”填为本轮精确名(如 `test/<id>-r2`)、“联测状态”填为相应枚举值(如 `RUNNING`),阶段字段始终保持 `S4`(不写 S4.5)。

## delivery.md 附加要求

启用本扩展的项目:"验证结论"须含 dev 联测结果摘要、实际 cherry-pick 的提交哈希及正式变更文档提交 hash;"部署上线注意"须区分**"master MR 冲突"**(阻塞交付)与**"未来同步至 dev 的兼容性风险"**(不阻塞交付,记为后续处理线索);并含**"变更文档"**与**"联测清理结果"小节**,前者记录文档路径和 feature/test 对应提交,后者按 verify.md 联测分支历史逐个列出每轮 test 分支的清理状态(已删除/待人工)。
