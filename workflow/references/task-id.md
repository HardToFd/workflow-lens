# 需求 ID

创建 PRD 目录、状态目录或分支前，先运行：

```powershell
python workflow/workflowctl.py validate-id <id>
```

工具以 `workflow/manifest.json` 为唯一规则源。不要在提示词或其他文档中复制正则和 Windows 保留名列表。

项目确定后仍需用 `git check-ref-format --branch "<完整分支名>"` 验证实际分支名。
