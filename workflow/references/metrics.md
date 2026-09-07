# 阶段过程度量

每次进入阶段先单独开始计时：

```powershell
python workflow/workflowctl.py metrics-start <id>
```

开始和结束时间统一保存并显示为 UTC+8 的 ISO 8601 格式，例如 `2026-08-31T10:45:09+08:00`。命令接收其他带时区的 ISO 时间时会转换为同一实际时刻的 `+08:00` 表示。

阶段完成、失败、阻塞、取消或准备进入任一回路前，执行：

```powershell
python workflow/workflowctl.py metrics-record <id> --outcome PASS `
  --waiting-seconds <有证据的等待秒数> --note "<证据或说明>"
```

- 先运行 `context` 确认可执行的项目与阶段，再开始计时；S3+ 的 `context`、`metrics-start`、`metrics-record` 使用相同 `--project <注册名>`。单项目可省略；S1/S2 为需求级。
- `metrics-start` 幂等：同一项目/阶段已有未结束计时时返回 `ALREADY_RUNNING`；同项目上一阶段未结束时拒绝开始新阶段。项目计时标记隔离，共享文档追加受进程锁保护。
- 有效 Codex session id 优先：使用 `CODEX_SESSION_ID` / `CODEX_THREAD_ID` 定位本机 JSONL，只读取 `token_count.info.last_token_usage`；重复的累计 `total_token_usage` 快照会跳过，再按阶段 UTC+8 起止时间所表示的实际时刻汇总。
- 没有 Codex session id 时，OMP 优先使用 `PI_SESSION_FILE`；OMP shell 未暴露该变量时，通过 `OMPCODE=1`、当前 cwd，并扫描近期 bash/eval `tool_execution_start` 的命令元数据定位当前主 session。`workflowctl` 以子命令和需求 id 消歧；并行 session 仍无法唯一定位则写 `NOT_AVAILABLE`，不得猜测。汇总主 session 及其同名目录中嵌套 agent 的 assistant `usage` 与 `model_usage`，不合并同 cwd 的其他并行 session。
- OMP 的 input = `input + cacheRead + cacheWrite`，cached input = `cacheRead`；reasoning 是 output 子集，`totalTokens` 必须等于 input + output。窗外、零用量、损坏或账目不一致的记录不计。
- 自动采集失败时文档写明原因并保留 `NOT_AVAILABLE`，不得用字数、耗时、模型或 0 冒充实测。其他运行环境可继续显式传入 `--input-tokens`、`--cached-input-tokens`、`--output-tokens`、`--reasoning-tokens`、`--total-tokens` 和 `--token-source`；显式值优先于自动采集。
- 阶段跨 Codex/OMP 会话恢复时，再次运行 `metrics-start` 会把当前 session 加入同一个 active marker，结束时合并各 session 的精确事件。
- `cached input` 属于 input，`reasoning` 属于 output；总量通常为 input + output，不重复叠加子集。
- 回流按下述唯一事件记录；`--rework-count`、有效/返工单元和旧效率比仅作历史兼容，不能取 max 或求和推断事件数，也不能用自填单元比比较需求质量。
- 用时从本阶段 `metrics-start` 计到本次 `metrics-record`，是记录区间墙钟时间，包含等待；并行项目区间可能重叠，合计不等于需求历时或人工工时。回路重新进入形成下一次尝试。
- `--waiting-seconds` 仅在有明确等待起止证据时填写，必须在本次用时范围内；缺失为 `NOT_AVAILABLE`，不要因结果为 BLOCKED 就把整个区间当等待或填 0。看板分别展示时间/Token覆盖率和部分合计；缺记录不按零计入平均。

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

`metrics.md` 是唯一对人输出的过程度量文档，只属于 `work/<id>/`。它和内部计时标记均不得进入目标项目需求分支、commit、MR/PR 或正式变更文档。

## 唯一返工事件

```powershell
python workflow/workflowctl.py rework-record <id> --event-id RW-001 `
  --type defect --loop L1 --project <注册名> --from-stage S4 --to-stage S3 `
  --occurred-at <带时区时间或NOT_AVAILABLE> --reason "<真实回流原因>" `
  --acceptance "<验收项编号>" --evidence "<verify.md小节或评审意见链接>"
python workflow/workflowctl.py rework-check <id>
```

- 类型：`defect` 实现/测试边界缺陷、`scope_change` 范围/合同变更、`baseline_adaptation` 基线适配、`environment` 环境阻塞、`workflow_migration` 流程迁移。回路独立记录为 L1/L2/L3/NONE；只有 defect 且实际 S4→S3 的 L1 事件计入项目 L1 熔断轮次。
- 同一事件只创建一次 ID；后续阶段在备注引用它。相同 ID/内容再次登记幂等，冲突 ID 拒绝写入。事件时间不清楚写 NOT_AVAILABLE，登记时间与发生时间分开，不从文档 mtime 猜时间。
- 旧文档数字可能混合累计/本轮口径，保留原始 token、时间及审批；按来源补事件，不凭数字生成事件。PARTIAL 表示仍有旧数字未完全对齐，已登记数量仅表示已核对的事件，不能把没有事件解读为零返工。INVALID 表示重复 ID 冲突或缺字段，须先修复记录。
- 历史需求若已有可复核的独立返工事件，按事件 ID 对齐；后续同一回路各阶段不重复计数，旧数字继续作为原始证据保留。


## 综合效率评分

看板以时间 35%、Token 25%、缺陷返工质量 40% 计算 0–100 分，整体按基准耗时加权。需要评分时，实施前按 [评分依据模板](efficiency-score.md) 冻结可比基准及验收项，验收后核对完整记录；缺失保持不可评分，不追填历史基准。详细公式与核对规则按需读取该参考，不增加每阶段必读内容。
