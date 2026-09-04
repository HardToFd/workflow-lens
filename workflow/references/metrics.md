# 阶段过程度量

每次进入阶段先单独开始计时：

```powershell
python workflow/workflowctl.py metrics-start <id>
```

开始和结束时间统一保存并显示为 UTC+8 的 ISO 8601 格式，例如 `2026-08-31T10:45:09+08:00`。命令接收其他带时区的 ISO 时间时会转换为同一实际时刻的 `+08:00` 表示。

阶段完成、失败、阻塞、取消或准备进入任一回路前，执行：

```powershell
python workflow/workflowctl.py metrics-record <id> --outcome PASS `
  --rework-count <n> --accepted-units <n> --rework-units <n> --note "<证据或说明>"
```

- `metrics-start` 幂等：同一阶段已有未结束计时时返回 `ALREADY_RUNNING`；上一阶段未结束时拒绝开始新阶段。
- 有效 Codex session id 优先：使用 `CODEX_SESSION_ID` / `CODEX_THREAD_ID` 定位本机 JSONL，只读取 `token_count.info.last_token_usage`；重复的累计 `total_token_usage` 快照会跳过，再按阶段 UTC+8 起止时间所表示的实际时刻汇总。
- 没有 Codex session id 时，OMP 优先使用 `PI_SESSION_FILE`；OMP shell 未暴露该变量时，通过 `OMPCODE=1`、当前 cwd，并扫描近期 bash/eval `tool_execution_start` 的命令元数据定位当前主 session。`workflowctl` 以子命令和需求 id 消歧；并行 session 仍无法唯一定位则写 `NOT_AVAILABLE`，不得猜测。汇总主 session 及其同名目录中嵌套 agent 的 assistant `usage` 与 `model_usage`，不合并同 cwd 的其他并行 session。
- OMP 的 input = `input + cacheRead + cacheWrite`，cached input = `cacheRead`；reasoning 是 output 子集，`totalTokens` 必须等于 input + output。窗外、零用量、损坏或账目不一致的记录不计。
- 自动采集失败时文档写明原因并保留 `NOT_AVAILABLE`，不得用字数、耗时、模型或 0 冒充实测。其他运行环境可继续显式传入 `--input-tokens`、`--cached-input-tokens`、`--output-tokens`、`--reasoning-tokens`、`--total-tokens` 和 `--token-source`；显式值优先于自动采集。
- 阶段跨 Codex/OMP 会话恢复时，再次运行 `metrics-start` 会把当前 session 加入同一个 active marker，结束时合并各 session 的精确事件。
- `cached input` 属于 input，`reasoning` 属于 output；总量通常为 input + output，不重复叠加子集。
- 返工只统计阶段重新进入：Gate B 打回、S4 FAIL、Gate C 评审回流、实质偏离退回 S2。同一轮内部的小修不计。
- 效率比统一为 `有效产出单元 / (有效产出单元 + 返工影响单元)`；分母为 0 时记 `N/A`。S1 用验收/影响项，S2 用获批改动项，S3 用完成改动项，S4 用验证项，S5 用交付项，S6 用归档项。
- 用时从本阶段 `metrics-start` 计到本次 `metrics-record`；回路重新进入会形成下一次尝试。

历史记录中已有 `NOT_AVAILABLE` 时，可只读预览后回填。Codex 传 session UUID；OMP 传主 session JSONL，参数均可重复：

```powershell
python workflow/workflowctl.py metrics-backfill <id> --stage S1 --stage S2 `
  --codex-session-id <session-uuid> --dry-run
python workflow/workflowctl.py metrics-backfill <id> --stage S1 --stage S2 `
  --omp-session-file <path-to-main-session.jsonl> --dry-run
python workflow/workflowctl.py metrics-backfill <id> --stage S1 --stage S2 `
  --omp-session-file <path-to-main-session.jsonl>
```

回填只替换对应阶段的 `Token 来源` 和 `Token` 两行，不改变结果、用时、返工、效率或备注。采集器只输出时间窗内的聚合 usage 元数据，不输出或写入用户消息、助手正文、工具参数和工具输出。

`metrics.md` 是唯一对人输出的效率文档，只属于 `work/<id>/`。它和内部计时标记均不得进入目标项目需求分支、commit、MR/PR 或正式变更文档。
