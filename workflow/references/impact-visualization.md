# S2 按需影响面分享图

影响面事实和审批依据分别以 S1 的 `analysis.md` 与 S2 的 `plan.md` 为准。默认不生成图；仅在跨项目、复杂异步链路或人类明确要求分享时使用本参考。图是辅助材料，不阻塞 S2 或 Gate B。

## 双技能分工

`config/skills.md` 默认停用 Archify 和 Diagram Design。确需生成图时，先确认两个适配器可用并按挂载表顺序执行；代理必须完整读取适配器指向的外部 `SKILL.md` 后再执行：

1. Archify 负责从代码证据生成候选 JSON、校验、交付自包含 HTML 和视觉检查结果。
2. Diagram Design 负责先选语义模式/主视觉类型，再检查信息层级、复杂度预算、可访问性、连接线和标签可读性。
3. Diagram Design 的意见必须回到 Archify 规格修正；最终 HTML 仍由 Archify 的交付流程生成，不允许通过审查后手改 HTML。最终 taste gate 失败时重新生成候选并复审。

任一适配器缺失、停用、入口失效，或任一技能没有真实执行证据，都不得宣称“双技能已执行”。

## 产物

- `work/<id>/impact-map.json`：Archify 规格，事实来自 `analysis.md`/`plan.md`，不虚构组件或关系。
- `work/<id>/impact-map.html`：自包含分享图；优先展示主调用/数据路径、变化节点、跨项目边界和验证落点，避免把文件清单逐项画成盒子。
- `work/<id>/impact-map-review.md`：记录两个挂载技能的入口与版本、Archify validate/deliver/visual-check 结果、Diagram Design 的类型/语义模式/尺寸/删减项与最终 taste gate。
- `plan.md`：审批摘要中链接上述 HTML 和 review，并写明图与文件级改动清单的一致性。

默认静态、中文、桌面文档宽度；节点超过技能预算时拆“总览 + 细节”，不缩字硬塞。Diagram Design 若触发首次样式档案选择，按其 gate 向人确认，不得静默采用默认皮肤。

## 按需图质量要求

图中每个变化节点可回指 `analysis.md` 的影响项或 `plan.md` 的改动项；每个跨项目/数据边界有方向；无多余关系；Archify 客观校验通过且 Diagram Design 最终审查无未解决硬失败。图未完成或审查未通过时如实标记，不影响 S2 或 Gate B 继续推进。
