# Coding Agent 全课程 Resources

## Knowledge

- [Week 4 讲义目录](../week4/)
  覆盖 Context Engineering、Working Memory、Long-term Memory、现代 RAG、LLM Wiki 与 Codebase RAG & Memory；用于为可验证 Coding Agent 构建“看见什么、记住什么、依据从哪里来”的信息供给层。
- [课程讲义：4.1 Context Engineering](../week4/4-1%20Context%20Engineering.pdf)
  用于：在 Token 预算内装配当前规则、代码、工具结果与证据，管理压缩、污染、缓存与调试报告。
- [课程讲义：4.2 Working Memory 与任务上下文](../week4/4-2%20Working%20Memory%20%E4%B8%8E%E4%BB%BB%E5%8A%A1%E4%B8%8A%E4%B8%8B%E6%96%87.pdf)
  用于：把目标、约束、风险、进度和带来源的执行事实维护成当前任务记录。
- [课程讲义：4.3 Memory 体系](../week4/4-3%20Memory%20%E4%BD%93%E7%B3%BB.pdf)
  用于：区分工作记忆与跨任务长期记忆，设计带来源、适用范围、失效状态和权限约束的可维护项目知识。
- [课程讲义：4.4 现代 RAG 系统](../week4/4-4%20%E7%8E%B0%E4%BB%A3%20RAG%20%E7%B3%BB%E7%BB%9F.pdf)
  用于：文档解析、分块、混合检索、重排、压缩、引用和端到端评估；避免将命中分数或引文编号误认为答案正确。
- [课程讲义：4.5 LLM Wiki 与知识资产治理](../week4/4-5%20LLM%20Wiki%20%E4%B8%8E%E7%9F%A5%E8%AF%86%E8%B5%84%E4%BA%A7%E6%B2%BB%E7%90%86.pdf)
  用于：将原始来源、草稿、已发布知识、依赖、版本、权限和维护日志组织为可追溯的知识资产。
- [课程讲义：4.6 Codebase RAG & Memory 项目演进](../week4/4-6%20%E9%A1%B9%E7%9B%AE%E6%BC%94%E8%BF%9B%E8%B7%AF%E7%BA%BF%20%E9%98%B6%E6%AE%B5%E5%9B%9B%EF%BC%9ACodebase%20RAG%20%26%20Memory.pdf)
  用于：将受治理的长期记忆与可追溯 RAG 接入 Codebase Agent，并以代码、测试和引用共同裁决冲突。
- [Week 1 讲义目录](../week1/)
  覆盖模型 API、Streaming、Prompt、Structured Output、LLM Gateway 与阶段一项目；用于建立所有后续 Agent 能力的受控模型调用底座。
- [课程讲义：2.1 Function Calling 与 Tool Use](../week2/1-FunctionCalling%20%E4%B8%8E%20Tool%20Use.pdf)
  本节主材料。用于：区分模型的候选动作与 Runtime 的执行权，设计 Tool Call / Tool Result 关联、Schema 和安全门禁。
- [OpenAI API：Developer quickstart - Extend the model with tools](https://platform.openai.com/docs/quickstart/make-your-first-api-request)
  官方文档。用于：核对模型通过工具扩展外部能力这一协议边界；不把模型输出误解为应用已执行的动作。
- [Model Context Protocol Specification：Server overview](https://modelcontextprotocol.io/specification/draft/server/index)
  MCP 官方规范。用于：理解 Server 向 Host 暴露 Tools、Resources、Prompts 的职责分工，以及 MCP 与单一 Function Calling 的关系。
- [课程讲义：3.3 State Machine 与 Checkpoint](../week3/3-3%20State%20Machine%20%E4%B8%8E%20Checkpoint.pdf)
  本节主材料。用于：区分会话续接与任务恢复，设计任务状态机、步骤执行记录、Checkpoint、审批门禁与恢复验收。
- [课程讲义：3.2 Planning 与任务拆解](../week3/3.2%20Planning%20%E4%B8%8E%E4%BB%BB%E5%8A%A1%E6%8B%86%E8%A7%A3.pdf)
  本课程的主材料。用于：执行方式选择、可验收子目标、证据和完成契约、计划修订、Loop 接入点。
- [课程讲义：2.2 Tool Runtime 设计](../week2/2-Tool%20Runtime%20%E8%AE%BE%E8%AE%A1.pdf)
  用于：Registry、Discovery、Snapshot、prepare/execute/finalize 生命周期与确定性边界测试。
- [课程讲义：2.3 MCP：Model Context Protocol](../week2/3-MCP%EF%BC%9AModel%20Context%20Protocol.pdf)
  用于：区分 MCP Host/Client/Server 与 Tools、Resources、Prompts，安全接入外部能力。
- [课程讲义：2.4 工具治理与安全边界](../week2/4-%E5%B7%A5%E5%85%B7%E6%B2%BB%E7%90%86%E4%B8%8E%E5%AE%89%E5%85%A8%E8%BE%B9%E7%95%8C.pdf)
  用于：权限状态机、审批、幂等/重试、编排、脱敏审计和副作用为零的验收。
- [课程讲义：3.1 从 Tool Agent 到 Agent Loop](../week3/3-1%20%E4%BB%8E%20Tool%20Agent%20%E5%88%B0%20Agent%20Loop.pdf)
  用于：多轮观察-行动循环、LoopGuard、Completion Contract 和端到端验证。
- [课程讲义：3.4 Sandbox 与执行边界](../week3/3-4%20Sandbox%20%E4%B8%8E%E6%89%A7%E8%A1%8C%E8%BE%B9%E7%95%8C.pdf)
  用于：路径、网络、进程与文件系统隔离，以及将安全规则覆盖到真实执行入口。
- [课程讲义：3.5 Agent Harness](../week3/3-5%20Agent%20Harness.pdf)
  用于：把 Context、Runtime、Loop、状态、治理和验收组织为可交付的 Coding Agent。
- [论文：ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629)
  原始研究论文。用于：理解 Agent 如何在行动结果反馈下更新后续行动，而不把“循环执行”误认为已经有显式计划。
- [论文：Plan-and-Solve Prompting](https://arxiv.org/abs/2305.04091)
  原始研究论文。用于：区分提示层面的先规划思路与运行时可校验的计划状态。
- [论文：SWE-agent: Agent-Computer Interfaces Enable Automated Software Engineering](https://papers.neurips.cc/paper_files/paper/2024/file/5a7c947568c1b1328ccc5230172e1e7c-Paper-Conference.pdf)
  真实软件工程 Agent 的研究论文。用于：把抽象的工具、环境反馈与代码修复任务联系起来。

## Wisdom (Communities)

- [SWE-agent GitHub Issues](https://github.com/SWE-agent/SWE-agent/issues)
  观察真实 Coding Agent 的边界问题、工具接口与可复现报告；先阅读问题和维护者讨论，再参与。

## Gaps

- 后续需结合一个实际 Java/Spring 项目，练习把计划证据映射到 Maven 测试、Git diff 和交付文档。

