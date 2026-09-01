---
description: 主入口:按协议从断点推进需求流水线
argument-hint: <需求id>
---

读 `AGENTS.md`，然后运行：

```bash
python workflow/workflowctl.py context $ARGUMENTS
```

只加载命令返回的当前阶段文件，执行或恢复需求 `$ARGUMENTS`。
