# Codex 与 OMP 双环境 Token 指标自动采集

## 背景

当前阶段指标采集器只识别 `CODEX_SESSION_ID` / `CODEX_THREAD_ID`，并从 Codex session JSONL 的 `token_count.info.last_token_usage` 汇总。OMP 环境不提供这些 Codex session id；其精确用量保存在 OMP session JSONL 的 assistant `usage` 与 `model_usage` 记录中，因此 `metrics-record` 在 OMP 下固定写入 `NOT_AVAILABLE: Codex session id is unavailable`。

## 目标

1. 在 OMP 环境中自动定位当前 session，并按阶段起止时间采集精确 Token 消耗。
2. OMP 汇总覆盖主代理以及该 session 下的子代理/顾问模型调用；不读取其他并行 session。
3. 保持 Codex 环境现有采集路径和统计口径，Codex 下不得因 OMP 目录不存在、格式差异或探测失败而报错。
4. 缺失、损坏或不一致的本地记录必须安全降级为带原因的 `NOT_AVAILABLE`，不得估算或以 0 冒充。
5. 支持对已有 `NOT_AVAILABLE` 阶段记录按明确的 Codex session id 或 OMP session 文件回填。

## Token 口径

- `input` 包含非缓存输入、cache read 与 cache write；`cached input` 单列 cache read，且仍是 input 子集。
- `output` 包含 reasoning；`reasoning` 单列但不重复叠加。
- `total = input + output`。
- OMP 使用单次调用的 `usage`，不把上下文窗口累计快照当成阶段增量。

## 验收标准

1. 仅存在 `OMPCODE=1`、没有 Codex session id 时，`metrics-record` 能自动定位当前 OMP session 并写入非空的精确 Token 五项。
2. 通过 `PI_SESSION_FILE` 显式提供当前 OMP session 时优先使用该文件，并汇总其关联的嵌套 agent JSONL。
3. 同一时间窗内主 assistant 用量、`model_usage` 用量及嵌套 agent 用量各计一次；窗外、零用量和无效记录不计。
4. 同时具备有效 Codex session id 与 OMP 标志时继续使用 Codex 采集，且不依赖 OMP 目录。
5. OMP 或 Codex 记录不存在、损坏或账目不一致时命令正常结束，指标写明 `NOT_AVAILABLE` 原因。
6. `metrics-backfill` 可用明确的 OMP session 文件回填历史 `NOT_AVAILABLE`，dry-run 不修改文件。
7. 现有 Codex 去重、时区、显式 Token 优先级和指标不变量全部保持。

## 非目标

- 不调用远端供应商用量 API。
- 不采集费用、消息正文、工具参数或工具输出。
- 不修改 OMP 或 Codex 自身的 session 文件。
- 不改变效率比、返工或阶段状态规则。
