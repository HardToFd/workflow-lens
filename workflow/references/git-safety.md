# Git 安全

1. 所有 Git 操作限定在 `state.md` 记录的目标工作目录。
2. 核对当前分支、基线 commit、工作区状态和预期提交集合。
3. 无法确认归属的修改立即阻止当前项目继续；不得自动 stash、reset、强制 checkout 或删除。
4. 创建分支前运行 `git check-ref-format --branch`。
5. 声明远端基线时先 fetch，再把基线解析成确定 commit。
6. 交付前确认分支、HEAD、工作区和提交范围均符合计划。
