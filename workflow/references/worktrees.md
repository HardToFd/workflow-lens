# Worktree 隔离与清理

同一仓库并行需求优先使用独立 worktree。默认路径为仓库同级的 `<仓库名>-worktrees/<需求id>`。

创建或复用前核对路径、分支和基线归属；成功后将绝对路径和“本工作流创建”标记写入状态。

S6 只清理带有该标记的临时 worktree。清理前：

1. 用 `git worktree list --porcelain` 核对精确路径。
2. 在目标 worktree 外执行检查和删除。
3. `git status --porcelain --ignored` 必须成功且输出为空。
4. 目标项目必须已经交付并通过闸口 C。

存在 tracked、untracked 或 ignored 文件，或任何检查失败时，不强制删除，记录为待人工处理。
