# 已掌握输出预算与截断边界

用户能正确说明 `max_tokens` 约束本次模型输出预算，超过该上限会导致输出截断。这为后续区分 Context Window、处理 `finish_reason=length`、以及拒绝消费残缺结构化输出建立了基础。

## Evidence

用户在 Week 1 第 1 课检索题回答：“本次输出预算，如果超出了 max_tokens，那么大模型的输出会被截断”。
