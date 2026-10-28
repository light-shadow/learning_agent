# 已掌握 Provider Adapter 的协议隔离职责

用户能准确指出各模型供应商的请求与响应格式应由 Provider Adapter（例如 DeepSeekProvider）归一化为统一结果，Agent Loop 不应感知供应商特有字段。这为后续 Gateway、流式事件和多模型切换设计建立了稳定边界。

## Evidence

用户在 Week 1 第 1 课回答：“模型供应商的层，比如 deepseekprovider；因为这个是各自模型有各自模型的独特格式，agent loop 不应该感知这个逻辑”。
