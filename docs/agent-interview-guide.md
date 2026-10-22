# Agent 面试必备知识点体系 · 2026 大厂面经（对应 dataquality-agent 项目）

> 目标：不是背八股，而是**每个知识点都能落回本项目代码（file:line）讲出工程深度**——面试官筛的是"遇到没见过的问题时的工程判断力"，不是概念复述。
> 检索来源：字节/阿里/腾讯/美团/百度/豆包 2026 面经 + llm-master、ai-agent-engineer-handbook、agent-interview 等公开题库（2026-05 ~ 2026-10）。**每节末尾有「来源」行做逐节溯源**；标注「综合/本项目」的为通用工程实践或本项目代码映射，非题库出处。

---

## 0. 面试表达方法论（先读这节）

面试官常见的高频追问是连续深挖，答案要按 **"30 秒要点 → 展开逻辑 → 结合本项目"** 三层组织：

1. **先给结论/边界**，不要上来铺技术栈。例：被问"为什么用 LangGraph"→ 先一句"因为它把 Agent 建模成有状态的有向图，我需要精确控制检测→归因→整改→审批的流程和 HITL 暂停点"，再展开。
2. **每个方案都带"代价"**。例：说 rerank 能提准，必须补"代价是多一段推理延迟，所以我用离线排序指标 + P95 延迟一起定候选数"。
3. **主动暴露踩坑与边界**。诚实说"哪里没做、为什么"比吹满更可信（例：案例库目前只有 4 条 demo，检索评测还停在单元级）。
4. **量化背书**。能报数字就报数字（本项目：检测 F1=1.0、归因 0.75、整改 0.50），但**必须能解释口径**（下面 §8 专门讲）。

**来源**：方法论综合（"30 秒要点 + 展开逻辑"表达结构整理自 51CTO《Agent 面试题 40+ 道》方法论；非题库出处）。

---

## 1. 知识点体系总览（知识地图）

| # | 知识模块 | 本项目代码出处 | 2026 高频度 |
|---|---|---|---|
| 1 | Agent 基础与架构 | `agents/graph.py` 整图 | ★★★ |
| 2 | Multi-Agent 编排 / LangGraph | `agents/graph.py`、`agents/inspect.py` | ★★★ |
| 3 | Function Calling / 工具调用 | `agents/diagnose.py`、`agents/tooling.py`、`llm.py` | ★★★ |
| 4 | 结构化输出 | `prompts.py`、`models.py`、`agents/remediate.py` | ★★★ |
| 5 | RAG（混合检索/RRF/Embedding） | `rag/retriever.py`、`rag/embedder.py`、`rag/cases.py` | ★★★ |
| 6 | HITL / 状态持久化 | `agents/hitl.py`、`api/runtime.py` | ★★☆ |
| 7 | 幻觉控制 / 安全护栏 | `agents/diagnose.py`、`tools/sql.py` | ★★★ |
| 8 | 评估 Eval / LLM-as-Judge | `eval/metrics.py`、`eval/judge.py`、`eval/harness.py` | ★★★ |
| 9 | 可观测 / 成本 | `observability/tracing.py`、`llm.py` | ★★☆ |
| 10 | 数据质量检测（项目特有） | `detection/rules.py`、`detection/stats.py`、`data/injector.py` | ★★☆ |

**来源**：本项目代码结构映射（非题库）。

---

## 2. Agent 基础与架构

**高频题**：
- Q：Agent 和普通 Chatbot / 单次调用有什么区别？
- Q：Agent 由哪几部分组成？（Planning / Memory / Tool Use）
- Q：Agent 和 Prompt Chain 的本质区别？何时用 Workflow、何时用 Agent？
- Q：单 Agent 何时升级多 Agent？多 Agent 的代价？

**答案要点**：
- Agent = LLM 为推理核心，多轮"**行动-观察**"闭环（ReAct），能据工具返回调整下一步；Chatbot 是单次无状态推理。判断标准是是否存在"行动-观察"循环。
- Workflow = 预定义 DAG、流程固定、确定性；Agent = 运行时动态分支、输入不确定。二者可结合：链管稳定流程，Agent 管链内某段的灵活分支。
- 多 Agent **不是高级，是最后手段**：任务边界清晰、需控制权转移或多轮回流才升级；代价是通信开销、状态一致、死锁、调试难、成本翻倍。

### 展开精讲：Agent 由哪几部分组成？（Planning / Memory / Tool Use）

标准框架来自 Lilian Weng《LLM Powered Autonomous Agents》的三件套，但光背框架不够——要能落到自己项目。

**一句话先定调**：Agent = LLM 当"大脑"负责推理，但 LLM 天生有短板——**不会记（无状态）、不会做（不能操作系统）、不会查（知识是训练时的静态快照）**。Planning / Memory / Tool Use 这三个组件就是给大脑补上这三块短板。

**① Planning（规划）= 拆任务 + 边做边纠偏**，分两个方向：
- 任务分解（Task Decomposition）：CoT 把复杂问题拆小步；ToT 做**树状搜索**（同节点探索多路径再选优）。
- 自我反思（Self-Reflection）：ReAct 每步"思考—行动—观察"即时纠偏；Reflexion **从失败中学习**（失败经验存进记忆，下次避开）。

规划分**静态**（预定义 DAG，流程写死）和**动态**（运行时据观察结果决定下一步）两种形态，真正的 Agent 是后者。

> 本项目：宏观静态规划（检测→归因→整改→审批→报告五段 DAG，`agents/graph.py:14`）+ 两段微观动态规划，且恰好是两种不同的循环范式——**归因节点是 ReAct（工具循环，边查边想，`agents/diagnose.py`），整改节点是 Executor+Critic（生成→评审→带反馈重写，Reflexion/Self-Refine 范式，`agents/remediate.py:125`）**。为什么这么分：巡检主干流程固定，纯动态会带来不可控跳步和成本，只有"根因分析"和"整改方案质量"这两段需要边做边纠偏。

**② Memory（记忆）= 让无状态 LLM 拥有上下文与积累**，分三层：

| 层级 | 作用 | 落地 |
|---|---|---|
| 短期记忆 | 当前会话上下文 | 上下文窗口内（in-context），受窗口限制 |
| 工作记忆 | 任务执行到哪、中间状态 | scratchpad / 状态对象 |
| 长期记忆 | 跨会话积累的经验/知识 | 外部存储（向量库/SQL），检索式召回 |

**RAG 本质就是长期记忆的检索式落地**：不塞进 prompt（放不下又贵），存外部、用时按相关性召回。

> 本项目：工作记忆 = `AgentState`（`models.py:75`，LangGraph 共享 state 即多 Agent 间的工作记忆）；长期记忆 = RAG 案例库（`rag/cases.py`，历史异常案例存成向量、按相似度召回）；短期记忆 = 归因循环里不断追加的 messages。三层都能对应。

**③ Tool Use（工具使用）= 给只会"想"的 LLM 补"手脚"**，补三个能力：
- 最新/外部信息（检索、查 API——训练数据是静态快照，问实时数据必须查）；
- **确定性计算（SQL/代码/计算器）——最该强调的一条：模型适合推理、不适合算准，让工具算、让模型解释**；
- 外部动作（发邮件、建工单）。

机制 = Function Calling / MCP，**核心是"执行权在程序手里"**：模型只输出"调哪个工具+填什么参数"的意图，真正执行的是代码，结果再回传。

> 本项目：归因挂 4 个只读工具（`agents/tooling.py:7`），特别强调"确定性计算交给工具"——SQL 诊断交给 `SafeSQL` 真执行（`tools/sql.py`），模型只决定查什么、怎么解释，绝不心算结果；且执行器被护栏约束（只读/白名单/禁多语句）。

**（常被补充的第四件套）Action / 执行器**：把 plan 变成对环境的真实动作、观察回流，即 ReAct 里的 "Acting"，与 Planning 里的 "Reasoning" 组成闭环。三件套里通常并进 Tool Use。

**一句话串成闭环**：Planning 决定做什么 → Tool Use 去执行 → 结果写进 Memory → 反思更新 Planning → 循环直到目标达成，即"思考—行动—观察"的主循环。

**高频追问**：
- 没有外部工具还算 Agent 吗？→ 算"弱环境 Agent"（仍有记忆+多步 CoT+自我验证）；判断标尺是**是否存在"行动-观察"闭环**，不是有没有工具。
- 长期记忆写入/检索时机？→ 写入：用户明确偏好 / 信息复用 N 次 / 会话结束总结（异步向量化）；检索：当前任务 embedding 召回 Top-K 相似记忆。
- 静态 vs 动态规划怎么选？→ 流程固定用 DAG（便宜可预测）、输入不确定用 ReAct（灵活），**生产常用"链管稳定段、Agent 管不确定段"的混合**。

### 展开精讲：长期记忆的写入与检索时机（读/写两侧的工程决策）

长期记忆的难点不是"存什么"，而是"**什么时候写、写之前怎么过滤、什么时候读、读多少**"——写少了记不住、写多了变噪声、读多了超预算。

**写入侧（4 个决策点）**：
1. **写入时机（三类触发信号）**：① 显式——用户明确表达偏好/事实（最高优先级）；② 复用——某信息被重复使用 N 次（如 3 次），说明有长期价值；③ 沉淀——会话/任务结束后的总结反思，抽取可复用知识（Reflexion"从失败里学经验"走的就是这条）。
2. **写入方式**：**异步**（不阻塞当前对话），先摘要压缩再 embedding 存入向量库/SQL。
3. **写入前过滤**：不是所有对话都存——去重（与已有记忆算相似度）、价值判断（有无复用价值）、时效（过期淘汰）。
4. **冲突处理**：新旧记忆矛盾时更新/覆盖/标记冲突，不能静默覆盖。

**读取侧（3 个决策点）**：
1. **检索时机**：新会话/新任务开始时，用当前目标 embedding 召回相关记忆（任务中途按需再召回，但要考虑成本）。
2. **检索方式**：当前目标 embedding → 向量检索召回 Top-K 相似记忆（K 常取 5~10），可加相似度阈值过滤——低于阈值不算，避免无关记忆污染上下文。
3. **注入预算**：召回的记忆 + 系统提示 + 工具定义一起拼进上下文，受窗口/token 预算约束，不能全塞。

**关键权衡（追问点）**：
- 为什么**异步写**？写入要"沉淀"（摘要+去重+判价值），且不能拖慢对话。
- 为什么**检索式读**而非全量？窗口有限 + 成本 + 无关记忆是噪声（污染注意力）。
- **记忆 ≠ 事实**：易变数据（实时股价、库存）不该进长期记忆，应该用 RAG/工具现查——记忆装的是"稳定的偏好/经验"，事实装的是"新鲜的外部数据"。

> **本项目映射 + 诚实边界**：我的"长期记忆"是 RAG 案例库（`rag/cases.py`），**读取侧完整**——归因时按异常症状 embedding 召回 Top-3 相似案例（`rag/retriever.py:25` 的 `search(k=3)`）；但**写入侧缺失**——案例是人工灌入的静态库，没有"整改成功/失败的案例自动回流写回"的闭环。这是我主动要讲的 gap：demo 阶段靠人工沉淀，生产要补"从每次巡检结果回流新案例"的写入链路（正是 Reflexion"从失败学经验写回记忆"的落地）。

**来源**：本子节的「写入三时机 + 异步写 + 先摘要再 embedding + Top-K(5~10)」表格口径来自阿里云《65题 AI Agent 全栈面试宝典》；「从失败学经验写回记忆」= Reflexion(Shinn et al. 2023)；学术根可追溯 Generative Agents(Park et al. 2023) 的 memory stream；过滤/阈值/注入预算/「记忆≠事实」为通用工程综合。

**本项目怎么答（话术）**：
> 我这个项目是**固定的 Pipeline 拓扑 + 局部动态循环**：整体走 LangGraph 的确定性 DAG（巡检→归因→整改→审批→报告，`agents/graph.py:14`），但"归因"和"整改"两个节点内部各有一套动态循环——归因是自由探索的 ReAct 工具循环（`agents/diagnose.py:87`），整改是 Executor+Critic 自纠循环（`agents/remediate.py:125`）。所以它是"Workflow 管骨架、Agent 管最不确定的那两段"——比纯 Agent 可预测、比纯 Workflow 灵活。为什么不用纯 Agent 端到端？因为数据质量巡检的主干流程是固定的，纯 Agent 会带来不可控的跳步和成本。

**来源**：Agent 三件套=Lilian Weng《LLM Powered Autonomous Agents》(2023)；长期记忆见上方子节标注；Agent vs Chatbot/Workflow、多 Agent 取舍=腾讯《27 道 AI Agent 真题》+ 字节/阿里力扣面经。

---

## 3. Multi-Agent 编排 / LangGraph

**高频题**：
- Q：LangGraph 的原理？相比 LangChain AgentExecutor 解决了什么？
- Q：节点、边、条件边怎么设计？state 是什么？
- Q：LangGraph 怎么区分不同用户/不同 run 的状态？（thread_id）
- Q：多 Agent 协作模式怎么选？Supervisor 还是 Handoff？

**答案要点**：
- LangGraph = 把 Agent 建模成**有状态的有向图（StateGraph）**：节点是处理步骤、边是转移、条件边按 state 路由；核心概念只有图/节点/边/状态四个。
- 相比 AgentExecutor：① 状态统一管理（所有节点读写同一 state）② 支持循环/分支/条件 ③ 状态可持久化（checkpointer）→ 可中断恢复、可回放调试 ④ 黑盒性低、可可视化。
- `thread_id`（`config["configurable"]["thread_id"]`）把"一次有状态任务"和身份绑定；换 thread_id = 新会话。
- Supervisor：控制权始终在调度者手里、全局兜底；Handoff：控制权转移给目标 Agent、源 Agent 退出。任务边界清晰 + 需多轮回流 → Supervisor（展开见下方精讲）。

### 展开精讲：多 Agent 协作模式怎么选？（Workflow / Supervisor / Hierarchical / Swarm）

**一句话定调**：选型是"控制权在哪"的光谱——从代码固定决策（Workflow）到 Agent 对等交接（Swarm）。**Handoff 不是和 Supervisor 平级的"模式"，而是 Swarm 的实现原语**，所以四种主模式 = Workflow / Supervisor / Hierarchical / Swarm（与原题"Supervisor 还是 Handoff"里 Handoff 的定位对齐）。

#### b.1 四种模式含义及特点

**先厘清三个易混概念（面试官最爱追问）**：
- **Supervisor ≠ Router**：Router 只做入口分类/一次分流；Supervisor 持续维护全局目标、任务图、依赖、结果与完成判断。Router 错只是错路由，Supervisor 错会全局放大。
- **Handoff ≠ Agent-as-Tool**：Agent-as-Tool 是主 Agent 把专家当工具调、自己保持 Owner；Handoff 是控制权/对话处理权转移给专家。前者"经理不交权"，后者"客服转接、源 Agent 下班"。
- **Swarm 有两层含义**：一是 OpenAI 早期开源的工具库名，二是"对等协作模式"这个抽象概念——别混为一谈。

**四种主模式对比**：

| 模式 | 决策方 | 控制权 | 特点 | 典型场景 |
|---|---|---|---|---|
| Workflow | 代码 | 固定 | 确定性最强、最便宜、最可 debug | 报表/ETL/固定审批 |
| Supervisor / Orchestrator | 中央 Agent | 集中 | 可 debug、全局兜底，但单点瓶颈 | 深度研究、动态拆分、任务边界清晰 |
| Hierarchical | 多层 Agent | 分层 | 上下文最省，但信息逐层失真 | 大规模团队（10+ 专家） |
| Swarm（核心原语 Handoff） | Agent 之间 | 对等 | 灵活、容错，但难 debug、易循环 | 客服、意图多变、需彻底流转 |

#### b.2 各模式详解及选型策略

**Workflow**：代码固定路径，最便宜最可预测，但无法处理输入不确定——适合流程本身确定、错误代价高的场景。

**Supervisor**：职责 = Routing + Task Decomposition + Worker Selection + Progress + Join + Termination。优点：控制点清楚、可 debug、全局兜底、支持多轮回流。缺点：编排者错误级联放大（一个错判断触发所有 Worker 并行重试，成本 ×2~3）；Token 膨胀；单点瓶颈。

**Hierarchical**：树形多层（Manager → Supervisor → Worker），每层加一个抽象层、上下文管理最好；代价是信息逐层摘要失真（目标/假设/证据在压缩中丢失）、延迟逐层累积（3 层每层 +2~4s）。

**Swarm / Handoff**：机制 = peer-to-peer 控制权转移（函数返回另一个 Agent 即 handoff，OpenAI Agents SDK 把 handoff 编译成 `transfer_to_xxx` 合成工具）。优点：灵活、局部自治、容错（任一 Agent 崩溃不影响其他）。缺点：难 debug、易循环（A→B→A 踢皮球）、上下文逐次丢失、审计难（"谁在何时做了什么决定"说不清，合规场景不可接受）。

**选型决策树（实用）**：
- 1 个 Agent + 工作流模式够用 → 别上拓扑（先做单 Agent 基线）；
- 2~4 个职责清晰的专家 → Supervisor / Orchestrator；
- 意图彻底流转、不再回头（咨询→下单→售后）→ Handoff（Swarm）；
- 10+ 专家、Supervisor 上下文预算爆 → Hierarchical；
- 高自治探索、容错 > 确定性 → Swarm。

> **本项目映射（选型策略落地，诚实 + 加分）**：我的项目其实**不是"自由协作的多 Agent"，而是"职责分离的流水线"**——五个节点是固定 DAG，`_route` 只是 Router 的一次条件分流（有没有高危→审批/报告），不是 Supervisor 的持续协调。为什么不用 Supervisor/Handoff：巡检流程固定串行、任务边界清晰、无需控制权转移或动态拆分，Workflow 最便宜可预测。这正好呼应"别急着上多 Agent"——如果以后要扩成"检测→多专家归因→多专家整改"的动态分工，才需要升级成 Supervisor（**演进规划见 §13**）。

#### b.3 工程陷阱和框架演进趋势

**2026 关键工程陷阱（数据背书，面试加分）**：Google Research + Princeton 独立研究——单 Agent（配足够工具）在 64% benchmark 上与最优多 Agent 持平，多 Agent 平均只 +2.1pp 准确率但 Token 膨胀 15×、成本翻倍。所以「多 Agent 不是高级，是最后手段」：只有出现可测量的职责冲突 / 工具过多混淆 / 上下文过长 / 权限隔离 / 子任务并行需求时才拆分。

**框架演进趋势（2026）**：LangChain 官方已将 `langgraph-supervisor` 包标记为不再维护，推荐迁移到 `create_agent` 的 subagents 模式——把子 Agent 包装成 `@tool` 来调用。这意味着 **Supervisor 模式本身也在往「Agent-as-Tool」方向收敛**：从"独立图节点的中央调度"变成"主 Agent 把子 Agent 当工具调"。面试时主动点出这个演进，既呼应「Handoff ≠ Agent-as-Tool」的辨析，又显得你在追踪框架最新动态。

**来源**：kaduoxzero/AI-Agent《Multi-Agent 协作模式》+ cdavid817 awesome-agent-tutorial《多Agent拓扑分类学》+ 腾讯云《一文解析多 Agent 编排架构模式全景》+ 牛客《agent面经-工作流编排与多 Agent》+ Anthropic orchestrator-workers。

**本项目怎么答**：
> 我用 LangGraph 而不是裸写循环，是要三样东西：① 状态机把流程固定住（`agents/graph.py` 的 `_route` 按"是否有高危整改"条件路由到审批或报告）；② checkpointer 支撑 HITL 暂停/恢复；③ state 作为多 Agent 间通信总线——每个节点是纯函数，返回"部分更新字典"，引擎负责合并（`agents/inspect.py` 的 docstring 详细讲了这个心智模型）。节点依赖（DuckDB 连接、模型客户端、工具）不走 state 而是闭包注入，因为 state 要被 checkpointer 序列化、而活连接没法序列化。

**来源**：wondercv《Agent开发工程师面试题库》（LangGraph 原理 / 单→多 Agent / 对比 AgentExecutor）+ LangGraph 官方文档 + llm-master。

---

## 4. Function Calling / 工具调用 / 结构化输出

**高频题**：
- Q：Function Calling 的原理？模型会"执行"函数吗？
- Q：工具调用怎么保证可靠性？模型编造参数怎么办（契约测试）？
- Q：结构化输出有哪几种强制等级？
- Q：工具数量多了怎么路由？

**答案要点**：
- 模型**不执行**函数，只输出"调哪个工具 + 填什么参数"的结构化意图（JSON），执行权在程序手里；程序执行后把结果回传，模型再综合。链路：定义工具 Schema → 模型决策 → 运行时解析执行 → 结果回传。
- 参数幻觉是重灾区（模型编不存在的枚举值 → 连环 400/500）。解法 = **契约防线**：工具网关 + Pydantic 校验 + 把错误结构化回传给模型助其自纠，而不是把"Bad Request"原样塞回。
- 结构化输出三级：L1 prompt 里"只输出 JSON"（最弱，会被无视）→ L2 API 级 function calling/tool_choice（schema 由 API 强制）→ L3 constrained decoding（每个 token 都校验，最强，如 OpenAI strict）。
- 工具过多：先把候选集缩小再让 LLM 填参——向量路由（工具 description 做 embedding）、分类/意图模型、层级目录（先选类再选工具）。

### 展开精讲：工具循环 / 契约测试 / 三级强制

**① 工具循环（Tool Loop）的协议细节**：一次 loop 严格遵循消息协议——模型返回 `tool_calls` 后，必须回填「assistant 消息（带 tool_calls）+ 每条调用各一条 tool 消息（tool_call_id 关联）」，下一轮模型才"看得到"结果。关键纪律：**模型只出"意图"，执行在代码**（模型既不适合算准、也会编造结果）。防失控靠三个闸：`max_steps` 步数上限、空响应 break、异常不中断（转成字符串回传）。

**② 契约测试（防参数幻觉）**：参数幻觉 = 工具名对、参数瞎填（编枚举值/格式错），导致连环 400/500 还烧 token。三道防线：**网关统一校验 → Pydantic/JSON-Schema 校验参数 → 把错误"结构化"回传**（告诉模型"status 必须是 pending|shipped|delivered"，而非塞回 "Bad Request"）。关键是第三条——给模型一个"自纠的钩子"。

**③ 结构化输出三级强制**：

| 级 | 手段 | 可靠性 |
|---|---|---|
| L1 | prompt 要求"只输出 JSON" | 最弱，会被无视 |
| L2 | function calling / `tool_choice`（API 按 schema 约束） | 强 |
| L3 | constrained decoding（逐 token 校验，OpenAI `strict`） | 最强，100% 合规 |

**L3（约束解码）机制**：本质是**生成时实时语法掩码**——把"格式合规"从模型概率预测问题变成确定性状态机约束。三个环节：
1. **状态追踪**：每生成一个 Token 前，内置语法解析器（JSON Schema / CFG / 正则）根据已生成序列实时算出当前合法语法状态；
2. **Logits 屏蔽**：把词表中所有不符合当前状态的 Token 的 Logits 置为 `-∞`，采样概率严格归零，只留合法候选；
3. **强制采样**：模型只能在合法候选集里选下一个 Token，物理上无法产出违规字符。

**三个核心特征**：① **事前拦截**——区别于 L1/L2 的事后校验/重试，L3 在生成中直接消除违规、零格式错误；② **解耦语义与语法**——只保证结构 100% 符合 Schema，不干预语义理解与事实准确性；③ **依赖底层支持**——必须推理引擎原生介入解码，无法用 API 兼容层或 Prompt 模拟。

选级看接口能力：DeepSeek 兼容接口只到 L2，所以本项目用 `tool_choice` 强制 + Pydantic schema；L3 需模型服务原生支持 strict 解码。

**本项目怎么答**：
> 归因 Agent 是**原生 function calling 工具循环**：4 个调查工具 + 1 个 `submit_diagnosis`，都转成 JSON Schema 喂给模型（`agents/tooling.py:7`、`agents/diagnose.py:92`）。两个关键设计：
> ① **用 function calling 实现强制结构化输出**——`submit_diagnosis` 伪装成"工具"，它的 schema 就是 `Diagnosis.model_json_schema()`（`prompts.py:99`），模型"调用"它交卷，参数天然满足 Pydantic 校验。
> ② **参数契约测试**——工具参数 `json.loads` 失败兜底空 dict、工具抛异常转成字符串"tool error:..."继续喂回（`agents/diagnose.py:103`、`_run_tool`），单个工具失败不打断整个循环。
> 整改 Agent 用 `tool_choice` 强制模型只能返回 `submit_remediation`（`agents/remediate.py:133`），但它**不是一枪定音**——而是 Executor+Critic 修订循环：生成 → 规则闸门(确定性) + Critic(LLM 语义) 两级评审 → 不合格带反馈打回重写，最多 3 轮，超限强制 high 交人工（`agents/remediate.py:125-147`）。所以同一个 `tool_choice` 技巧，归因用它"收敛出结论"、整改用它"每轮约束输出格式"，收敛逻辑各不相同。

**来源**：阿里云《工具调用与结构化输出》+《Function Calling 契约测试》+ llm-master agent_interview + JoshithReddyAleti《Week3 Tool Calling》。

---

## 5. RAG（混合检索 / RRF / Embedding）

**高频题**：
- Q：纯向量检索有什么问题？为什么混合检索？
- Q：RRF 是什么？k 取多少？
- Q：检索之后为什么还要 Rerank？检索和 Rerank 的区别？
- Q：RAG 效果差，先查什么？

**答案要点**：
- 纯向量三问题：① 精确匹配不行（"RFC 7231"搜不到原文）② 专业术语召回差（"HPA"对不上"自动扩缩容"）③ 专有名词/编号/缩写易丢。混合 = 向量（语义）+ BM25（关键词）取长补短。
- RRF：`score(d) = Σ 1/(k + rank_i(d))`，k 常取 60；不依赖原始分数尺度，只比排名，适合各路分数不可比时。
- 检索 = 粗筛（Bi-Encoder 快但粗）；Rerank = 精排（Cross-Encoder 把 query+doc 拼一起精算）。标配"召回 Top-20 → Rerank 取 Top-5"。
- RAG 效果差：先分"检索问题还是生成问题"→ 看 Recall@K → 抽样看 chunk 与召回结果 → 再决定改 embedding/chunking/rerank。

**本项目怎么答**：
> 归因的"相似案例检索"是 dense（语义）+ BM25（关键词）两路召回、RRF 融合（`rag/retriever.py:25` 的 `search` 和 `:53` 的 `_rrf`，k=60）。Embedding 是可插拔的：配了 `EMBEDDING_BASE_URL` 走 OpenAI 兼容的 BGE-M3，否则词袋 fallback（`rag/embedder.py:63`）。
> **RAG 深度（已做）**：BM25 现在是**标准的**（IDF + k1/b 长度归一化，`rag/retriever.py` 的 `_bm25`），并补了 `llm_rerank`（`rag/rerank.py`，LLM 精排，Cross-Encoder 的 LLM 版）和检索评测 `recall_at_k`/`mrr`（`eval/retrieval.py`）。**诚实边界**：案例库仍只有 4 条 demo，检索评测停在单元级，真正的 Recall@K 曲线要等案例库规模化、有标注集才能跑。

**来源**：llm-master rag_interview + 卡码笔记《RAG 大厂面试题汇总》+ 腾讯《为什么你的 RAG 检索不到答案》。

---

## 6. HITL / 状态持久化

**高频题**：
- Q：LangGraph 怎么做 human-in-the-loop？
- Q：`interrupt()` 的机制？怎么 resume？
- Q：暂停的状态怎么持久化？进程重启怎么办？
- Q：checkpointer 为什么是必须的？

**答案要点**：
- HITL 三件套：**checkpoint（状态持久化，key 用 thread_id）+ interrupt（挂起执行、把 payload 交给调用者）+ resume（`Command(resume=X)` 把人工决策送回，成为 `interrupt()` 的返回值）**。
- `interrupt(payload)` 是"两个方向两个时刻"：参数是"节点→调用者"（吐出待审批清单），返回值是"调用者→节点"（人工决策原样返回）。
- 持久化靠 checkpointer，所以暂停可以持续任意时长、跨进程/跨机器续跑；生产必须换掉 MemorySaver（SqliteSaver/PostgresSaver）。
- 两个前提：① build_graph 传 checkpointer ② 两次 invoke 用同一个 `thread_id`。

**本项目怎么答**：
> 我的审批节点用 `interrupt({"pending": [...]})` 把高危整改清单吐给前端，人工在前端点 approve/reject，后端 `Command(resume=decision)` 恢复（`agents/hitl.py:46`、`api/runtime.py:44`）。关键设计：**只有高危方案才进审批**（`Remediation.requires_approval`，`models.py:37`），低危直接走报告——减少打断。**Checkpointer（已修复）**：已从 `MemorySaver` 换成 `SqliteSaver`（`api/wiring.py`），审批状态落盘 SQLite、跨进程重启不丢；更高并发/多实例再换 Postgres。

**来源**：LangGraph 官方文档（HITL / Interrupts）+ CSDN《LangGraph 1.2 持久化与人工审核》。

---

## 7. 幻觉控制 / 安全护栏

**高频题**：
- Q：Agent 里幻觉有哪几种？分别怎么治？
- Q：你们怎么约束 LLM 幻觉？约束后还幻觉怎么办？
- Q：工具调用系统的安全怎么保障？（prompt injection、权限）

**答案要点**：
- 幻觉分类：知识幻觉（编事实）、工具幻觉（调不存在的工具）、参数幻觉（参数瞎填）、证据幻觉（引用不存在的证据）、行动幻觉（执行不该执行的）。**先分类再对症**，不要一上来就"写 prompt 让它别编"。
- 四层防线：① Prompt 约束（管边界，管不住全部）② 工具调用约束（防乱行动：白名单/参数校验）③ 证据约束（RAG/工具提供事实，回答有据可依）④ 输出校验（生成完不是结束：规则/第二模型/引用回查）。
- 约束后还幻觉：拦截、降级、转人工、trace 复盘、eval 治理、监控告警。
- 工具安全：prompt injection（网页内容注入指令）、权限越界（只该读却删）→ 输入分类器 + 参数校验 + 权限检查 + 输出清洗。

**本项目怎么答（这是本项目最亮的卖点之一）**：
> 我针对"**证据幻觉**"做了硬约束——归因 Agent 的 `evidence_chain` 由代码记录每次真实工具调用，模型提交结论时自述的 `evidence_chain` 被 `args.pop` 直接丢弃、改用真实调用历史（`agents/diagnose.py:116`）。再加一道"**证据闸门**"：一个工具都没调就想提交结论，直接拒绝并逼它先去收集证据（`agents/diagnose.py:108`）。这两条把"模型编造调查过程"这个最隐蔽的幻觉堵住了。
> **工具安全**：SQL 工具走 `SafeSQL`——只准 SELECT、禁多语句、表白名单、行数上限（`tools/sql.py:11`），从工具层就断了"Agent 乱写 DELETE"的可能。
> **输出校验（第四层防线）**：整改 Agent 的 Executor+Critic 循环就是活例子——方案生成后先过**确定性规则闸门**（`_rule_check`：SQL 写操作缺 WHERE、引用不存在的表、高危漏标 risk_level，`agents/remediate.py:91`），能硬判定的错误不花 LLM；规则通过再交 **LLM Critic** 判语义（action_type 归类对不对、建议是否真能修根因、risk_level 判得准不准，`agents/remediate.py:107`）。不合格带反馈打回重写、超 3 轮强制 high 转人工（`agents/remediate.py:147`）——这就是"生成完不是结束，规则/第二模型再校验一道"。
> **诚实边界**：`matched_cases`（命中的案例 ID）目前还是模型自述、代码没回填，所以"没查案例却谎称命中"拦不住——这是我明确知道、下一步要像 evidence_chain 一样回填的洞。

**来源**：llm-master agent_hallucination_control_interview + agent-interview hallucination + 阿里云《幻觉检测与线上监控》。

---

## 8. 评估 Eval / LLM-as-Judge

**高频题**：
- Q：Agent 怎么评测？为什么不能只看准确率？
- Q：LLM-as-a-Judge 的优缺点、有哪些 bias？
- Q：离线评估和在线评估怎么分工？
- Q：怎么证明你的评估指标靠谱？

**答案要点**：
- Agent 评测不是单一准确率，而是"任务结果 + 执行过程 + 工具调用 + 成本 + 延迟 + 稳定性 + 安全"的全链路体系。传统测试断言确定输出，Agent 评估输出是"程度而非布尔"，且要评轨迹不只评结果。
- LLM-as-Judge：可扩展、有 nuance，但有 bias（位置偏差、长度偏差、自我偏好、奉承偏差）；关键判定尽量用**可验证信号**（代码跑通、SQL 结果），judge 用于开放维度；必须**人工抽检校准**一致性。
- 离线 = 固定集回归门禁（快、可复现）；在线 = 真实流量采样（看真实分布/成本/失败模式）。两条腿缺一不可。
- 指标可信靠：ground-truth 对齐键规约 + 分型切片 + 人工校准 judge。

**本项目怎么答（数字 + 口径是核心）**：
> 我的评估地基是 **ground-truth**：注入器把干净数仓注入 7 类异常，同时记录每条的真实根因类别（`data/injector.py:11` 的 `ROOT_CAUSE_CATEGORY` 与 `Diagnosis.root_cause_category` 枚举对齐）。归因正确率不是"比文本像不像"，而是比**结构化类别是否一致**（`eval/metrics.py:96`）。
> **整改成功率用"复检口径"**——不是看 SQL 长啥样，而是"应用 fix_sql 后重跑检测、异常是否消失"（`eval/harness.py:42`）。而且我按**可逆/数据丢失分型**：可逆异常（重复、负值）SQL 能修、成功率 1.0；数据丢失异常（删行、置空）原始值已毁、只能上游重跑、成功率 0.0（`eval/harness.py:14` 的 `REVERSIBLE_TYPES`）。这个分型印证了"SQL 不是万能"的边界，比一个笼统的 0.50 更有说服力。
> **LLM-as-Judge**：我用 rubric 让强模型给归因/整改质量打 1~5 分，但配了 `judge_agreement` 做人工抽检校准（`eval/judge.py`），解析失败降级最低分不抛异常。**真跑了校准**（`scripts/run_judge_calibration.py`，6 条标注集），一致率一路从 prompt 化 JSON 的 **16.67%** → 结构化输出 + rubric 锚点 **38.89%** → 加根因上下文 **44.44%**（exact）/ **77.78%**（±1 容差）。三个关键经验：① DeepSeek function calling 会**截断含空格的 property name**（"action_type 归类"→"action_type），维度名必须无空格；② 不给 judge 根因，它会把"删孤儿行"的 fix_sql 判成满分（orphan 该 ticket 重跑上游）；③ exact 1~5 太苛刻（4 vs 5 方向一致却判不一致），±1 容差才是 Likert 量表"rough agreement"的合理口径。结论：judge **方向性正确但精确档位有噪声**，所以关键判定（SQL 能否跑通、异常是否消失）用可验证信号，judge 只用于开放维度。

**来源**：agent-interview evaluation + MisterBooo《评估与监控图解》+ AgentGuide《模型评估篇》+ 阿里云《Agent 怎么评测》。

---

## 9. 可观测 / 成本

**高频题**：
- Q：Agent 为什么比传统服务更需要 Trace？怎么追踪？
- Q：Token 成本怎么归因？重试浪费了多少？
- Q：结构化日志和 Trace 区别？

**答案要点**：
- 传统 APM 的核心单元是 HTTP 请求，Agent 的核心单元是**推理链**（意图→规划→工具→多轮模型→子 Agent），必须按 Task/Trace/Span/Event 分层追踪。
- Token 消耗在同一功能下可能波动十倍，没有细粒度 trace = 成本失控；要能回答"哪个 Agent/模型/工具烧了多少 token、重试浪费多少"。
- Trace = 因果树（定位单次链路），Log = 事件流（解释状态迁移），Metric = 趋势告警（P95/错误率/成本），四者用 trace_id 关联。

**本项目怎么答**：
> 每次 LLM 调用都埋一个 `Span`（记录输入/输出/token/耗时），`CostLedger` 累计 token/成本/调用次数（`observability/tracing.py`、`llm.py`）。可观测是**旁路**：`Tracer` 永远记内存、`backend` 可选（`end_span` 里 `if self.backend is not None` 才转发），监控挂了不拖垮主流程；`LangfuseBackend` 惰性导入 + 未配 key 就 no-op，由 `wiring.py` 按 `LANGFUSE_PUBLIC_KEY/SECRET_KEY` env 接进链路。评估报告直接输出 `total_tokens/total_cost/llm_calls/latency`（`eval/metrics.py`），所以"单次巡检 ~78 万 token / ~39s"是有账可查的。
> **Token 计数（已修复）**：从「按字符估算」改为**读 API 返回的 `usage.total_tokens` 真实计数**（`llm.py:20` 的 `_count_tokens`），客户端不返回 usage 时才回退字符估算兜底。所以"78 万 token"现在有 API 依据，成本台账可信。

**来源**：agent-interview observability + 阿里云《RDS Agent 可观测》。

---

## 10. 数据质量检测三层（项目特有，映射到通用考点）

**高频题（映射）**：
- Q：哪些检测该用规则/统计、哪些该用 LLM？（对应"模型 vs 确定性计算的边界"）
- Q：怎么让异常注入可复现？（对应"评估的地基"）

**答案要点**：
- **确定性优先、LLM 兜底**：能规则断言的（主键重复、负值、null 率）用 0-LLM 规则，最快最可解释；统计（z-score/PSI/血缘水位线）学历史基线报偏差；LLM 语义检测最后兜底。这是成本与可靠性的分层。
- 注入器用固定 seed（`config.py:13` `seed=42`）保证 ground-truth 可复现——评估的地基必须可复现。

**本项目怎么答**：
> 检测三层现在齐全：L0 规则断言（`detection/rules.py`，0-LLM）、L1 统计（`detection/stats.py`：血缘断裂/停更/schema 漂移/**volume(z-score)/distribution(PSI)**）、L2 LLM 语义（`detection/semantic.py`：采样 DWD 表让 LLM 找规则/统计抓不到的语义异常，`semantic_model` 缺省跳过）。分层逻辑：确定性优先、LLM 兜底——规则最快最可解释，统计学历史基线，LLM 只兜底语义层。

### 展开精讲：数仓分层为什么是「检测导向」而非「分析导向」？

**一句话定调**：这个数仓（`data/warehouse.py`）不是标准星型模型，而是面向数据质量检测的「ODS → DWD → DWS」轻量分层——它要喂给三层检测（L0 规则 / L1 统计 / L2 语义），不是给 BI 出报表。

**分层与表分类**：
- ODS：9 张原始 CSV 落库（`warehouse.py:9-19`）。
- DWD：事实表 = dwd_orders / dwd_order_items / dwd_payments / dwd_reviews（交易流水）；维度表 = dwd_products / dwd_sellers / dwd_customers / dwd_geolocation（业务实体）。
- DWS：daily_metrics（日粒度指标，L1 volume/distribution 的对比基线）。

**三个「有意不做」的取舍**（面试最值钱）：
1. **不建统一事实宽表**：星型模型的宽表是给分析 join 用的；检测要的是「各表独立、靠 FK 列逐对校验」，所以 DWD 各表仅通过 order_id/product_id/seller_id/customer_id 逻辑关联，不 flatten。
2. **不建真实 FK 约束**：DuckDB `CREATE TABLE AS` 不加约束，「关联」只是列值能对上；引用完整性交给检测层 `check_orphan` 逐对校验兜底——「数据不强制、检测来补缺」。
3. **DWS 读 ODS 不读 DWD**：daily_metrics 直接 JOIN ODS 的 orders/order_items，因为这两个表的数值列在 ODS 已是干净 DOUBLE、且只按日期聚合；products 重量这种需要 TRY_CAST 的列才走 DWD。

**translation 表为何「加载但不用」**：product_category_translation 在 ODS 被加载（`warehouse.py:18`），但没建 DWD、也没被任何 SQL 引用——因为当前检测不用品类语义：L1 distribution 只查 order_status、L2 语义只采样 dwd_orders/dwd_order_items。需要英文品类名时再补。

**来源**：本项目代码映射（非题库；对应"模型 vs 确定性计算边界"通用考点 + "数据治理底座（数仓分层/血缘/质量）" A 家族 JD 硬门槛）。

---

## 11. 差距分析 → 新的优先级待办

> 原则：**第一优先级 = 面试被问到的概率 × 被问穿的风险**，其次才是功能完备。

### 🔴 P0 —— 会被问穿、且影响"数字可信度"的硬伤（先补）

1. ~~**Token 计数换成真实值**~~ ✅ **已完成**（`llm.py` 读 `usage.total_tokens`，101 tests passed，已提交 `8c35e48`）。
2. ~~**LLM-as-Judge 校准闭环**~~ ✅ **已完成**（`scripts/run_judge_calibration.py` 6 条标注集：一致率 16.67%→44.44% exact / 77.78% ±1，详见 §8）。
3. ~~**HITL 换持久化 checkpointer**~~ ✅ **已完成**（`api/wiring.py` 换 `SqliteSaver` + `config.py` 加 `checkpoint_path` + `pyproject.toml` 加 `langgraph-checkpoint-sqlite`，101 tests passed）。
4. ~~**matched_cases 像 evidence_chain 一样回填**~~ ✅ **已完成**（`agents/diagnose.py` 的 `_matched_case_ids` 回填真实命中 ID + `tooling.py` 的 `cases_func` 累积，已提交 `c8aa650`）。

### 🟡 P1 —— ✅ 已完成（2026-10-19）

5. ~~RAG 深度~~ ✅ 标准 BM25(IDF) + `llm_rerank` + `recall_at_k`/`mrr`（`rag/retriever.py`、`rag/rerank.py`、`eval/retrieval.py`）
6. ~~L2 语义检测~~ ✅ `detection/semantic.py`（LLM 采样 DWD 表找语义异常，`semantic_model` 缺省跳过）
7. ~~L1 volume/distribution 接线~~ ✅ `detect_volume`(z-score) + `detect_distribution`(PSI) 接入 `run_detection`

### 🟢 P2 —— 加分故事，不是必问

8. **数据丢失异常 0.0 的叙事**：不是要去解决它，而是把它当成"SQL 非万能、需上游重跑"的踩坑素材讲（已有 `REVERSIBLE_TYPES` 分型背书）。
9. **血缘从数仓元数据自动采集**（`data/lineage.py:4`）：现在硬编码，讲得出"为什么 demo 硬编码、生产该接元数据"即可。
10. **Langfuse usage 拆分 input/output**（`observability/tracing.py:77`）：锦上添花。

### 一句话结论

> 功能完备性让位于面试可辩护性：**先让"已实现的东西"经得起拷问（token 准、judge 有校准、HITL 持久化、防幻觉闭环），再谈"没实现的东西"（L2、RAG 深度）**——后者用"诚实边界 + 工程判断"就能在面试中转化为加分项，不必急着堆功能。

**来源**：本项目差距分析（非题库）。

---

## 12. 质量工程进阶（可观测 / 可评测 / 可调试 / 可进化）

> 依据 `docs/2026Agent会干活还不够-2026年正进入可观察可评测可进化时代.md`：Agent 工程正从"能力工程"走向"质量工程"，四关键词——可观测 / 可评测 / 可调试 / 可进化。

### 现状判定

| 关键词 | 本项目现状 | 判定 |
|---|---|---|
| 可观测 | `Tracer` 步骤级 Trace：节点/LLM/工具/检索都埋 span、按 parent 组树（render_tree/summary_by_name） | 🟢 较强 |
| 可评测 | Outcome(F1/归因/整改/端到端) + Trajectory(过程合格率/冗余/schema优先) + Judge 校准(44%/78%) + RAG(Recall@K/MRR) | 🟢 强 |
| 可调试 | 有 `evidence_chain`（真实工具历史）+ Failure Taxonomy（漏检/归因错/整改失败分型） | 🟢 较强 |
| 可进化 | 缺 Data Flywheel（一次性 eval，非闭环） | 🔴 缺 |

### 待补清单（P1 → P2 → P3）

- **P1（材料最现成、面试最加分）**：
  1. ~~**Trajectory Evaluation**~~ ✅ **已完成**：`eval/trajectory.py` 用 `evidence_chain` 规则化评过程（无冗余重复调用 / 用 SQL 前先查 schema / 证据 ≥2 工具），接入 EvalReport、`run_eval.py` 输出轨迹质量，129 tests 全绿。
  2. ~~**Failure Taxonomy**~~ ✅ **已完成**：`eval/metrics.py` 的 `classify_failures` 把端到端失败按「漏检 / 归因错 / 整改失败 / 成功」四桶分型，`run_eval.py` 输出失败分型，134 tests 全绿。
  3. ~~**步骤级 Trace**~~ ✅ **已完成**：`Span.parent` + ContextVar 自动父挂，节点/LLM/工具/检索都埋 span（node:*/tool:*/retrieve/llm），`render_tree`/`summary_by_name` 定位最慢一步，140 tests 全绿。
- **P2**：
  4. **Safety Evaluation**——prompt injection / 权限越界 / 危险操作的测试用例（不止 SafeSQL 机制，要有评测）。
  5. **Regression 进 CI**——benchmark 集 + eval + 对比 baseline 的回归脚本。
- **P3**：
  6. **Data Flywheel 完整闭环**——低分 case → 失败挖掘 → 人工复核 → 回归集 → 优化 → 离线 eval → A/B → 上线。

> **简历定位**：能写，但突出真有的（ground-truth 评测、复检口径、Judge 校准、只读护栏）；别把"可进化"吹满——补完 P1 三块后才能理直气壮说"质量工程"。

**来源**：用户提供的 2026 Agent 质量工程文档 + 本项目对照分析。

---

## 13. 项目演进规划：真·多 Agent（Supervisor）——把"多 Agent"关键词做实

> 定位：**不是新增项目，而是把 `dataquality-agent` 从"单图流水线"演进成"单图 → 多 Agent"两代**，补齐当前简历最大拷问点。

### 为什么做

- 当前是单图 5 节点 DAG，**不是真多 Agent**（§3 已诚实标注）；但简历"核心能力"写了"多 Agent 编排"，而 22 份 JD 里"多 Agent 协作/编排"出现 14 次。面试官最可能戳的就是"你这算真多 Agent 吗？"。
- 补法两条：弱化措辞（回避），或把架构做实（**推荐**）。

### 做什么（复用业务，改架构不改业务）

- 复用"数据质量巡检"业务 + ground-truth 注入器 + 复检口径 + 评测框架，**不换业务、不从零搭评测**（换业务 = 白扔现有评测资产）。
- 架构：单图 5 节点 → **Supervisor + 4 专职 Agent**（orchestrator 分诊 + 规则检测 / 血缘归因 / SQL 排查 / 案例检索），各 Agent 独立 system prompt + 工具集 + 预算。
- 对照指标：归因正确率、单次 token、latency、失败分型——与单图版 before/after 对比（这才是"可进化"的证据）。

### 简历怎么呈现（一个项目，两代演进）

**不拆成两个项目**——同一个业务换个架构写两遍 = 注水，必被识破。写成两代演进并主动讲"为什么改"：

> "第一版单图 5 节点流水线，职责耦合、单点故障整链中断、token 预算难控；重构为 Supervisor + 4 专职 Agent，归因正确率 0.75 → X、单次 token 78 万 → Y。"

一个有演进史的项目 > 两个平铺项目，同时证明架构判断力 + 可进化（呼应 §12 Data Flywheel）。

### 时机（排在 §14 数据基座 + §12 P1 之后）

整体顺序：**§14 数据基座（先铺实数据）→ §12 P1（补可评测证据）→ §13 多 Agent（再做演进）**。先花 1~3 天补 §12 的 P1（Trajectory Eval / Failure Taxonomy / 步骤级 Trace），再花 1~2 周做 Supervisor 版；否则"可评测"证据没补齐又开新坑。

**来源**：用户 2026-10-21 简历复盘（"项目数量 vs 深项目"决策 + 多 Agent 缺口）+ §3 选型决策 + §12 质量工程。

---

## 14. 数据基座升级：把 Olist 9 表用起来（去 demo 味）

> 定位：当前 demo 味不是"数据小"，是"数据接进来但没用起来"——`warehouse.py:9-19` 已映射全部 9 张 Olist 表，但 DWD/DWS/检测只用了 orders + order_items，其余 7 张表（payments/reviews/products/sellers/customers/geolocation/类别翻译）落 ODS 后 0 引用。**先铺数据基座，再谈 P1 评测和多 Agent 演进**（顺序：§14 → §12 P1 → §13）。

### TODO 清单（逐条勾选）

| # | 任务 | 改哪个文件 | 面试怎么讲 |
|---|---|---|---|
| 1 | ~~确认 9 张 CSV 是否齐全~~ ✅ **已确认**：9 张全齐，在 `/data/home/hermes/olist/`（2026-10-12 下载，共 ~123MB）；此前"搜不到"是 kaiChen 读不了 hermes 家目录（750）所致，非数据丢失 | — | 前置依赖，已通过 |
| 2 | ~~DWD 补全~~ ✅ **已完成**：6 张新 DWD（payments/reviews/products/sellers/customers/geolocation）用 TRY_CAST 类型规范化（空串→NULL）；真实 Olist 验证 8 张 DWD 全建（orders 99441 / items 112650 / payments 103886 / reviews 99224 / products 32951 / sellers 3095 / customers 99441 / geolocation 1000163），115 tests 全绿 | `data/warehouse.py` | "9 表星型模型，事实表 + 维度表都做了类型规范化" |
| 3 | DWS 补聚合：`seller_metrics`（GMV/单量/评分）、`category_metrics`（品类）、`payment_summary`（分期/支付方式） | `data/warehouse.py` | （目标，未做）volume/distribution 从单基线扩成多基线（现 volume 查 daily_metrics、distribution 查 dwd_orders） |
| 4 | ~~跨表一致性检测~~ ✅ **已完成**：`check_amount_mismatch`/`check_state_conflict`/`check_zip_inconsistency` + `run_consistency_checks`，真实 Olist 检出 380 金额不一致 + 609 状态矛盾 + 8556 邮编矛盾；评测改 **baseline-aware**（真实问题从误报扣除，检测 F1 仍 1.0） | `detection/rules.py` + `eval/metrics.py` + `scripts/run_eval.py` | "检测在真实数据上抓到真实问题，评测口径诚实" |
| 5 | ~~孤儿外键扩展~~ ✅ **已完成**：`check_orphan` 铺满 order_items→products/sellers、payments→orders、reviews→orders、orders→customers（真实 Olist 全 0，注入才触发）；orphan 注入改删叶子父表 products 避免爆炸半径 | `detection/rules.py` + `scripts/run_eval.py` | "FK 网全铺，注入口径与 ground-truth 对齐" |
| 6 | 血缘做实：让 `lineage.py` 的边对应真正 build 出来的表（别再"挂地图不打仗"） | `data/lineage.py` | （目标，未做）血缘和真实 DWD/DWS 对齐，可回答"这字段源头在哪" |
| 7 | ~~注入器扩展~~ ✅ **已完成**：`inject_amount_mismatch`/`inject_state_conflict`/`inject_zip_inconsistency` + ROOT_CAUSE_CATEGORY 对齐，123 tests 全绿。注：这三类是 **always-on**（真实数据基线就命中），注入 F1 平凡（=1.0），其「证明」靠真实基线（380/609/8556）而非注入 F1 | `data/injector.py` | "注入器覆盖全检测类型；always-on 检测靠真实基线证明" |

**验证**：`pytest` 全绿 + `run_eval.py` 复跑，同步更新简历/文档里的数字（F1 / 归因 / 整改 / 端到端 / token）。

> **去 demo 味的真解药是"小而完整 + 可复现"，不是堆体量**：面试官不在乎 100 万行 vs 1 亿行（DuckDB 都能跑），在乎"数仓模型像不像真的、检测能不能抓到真实问题类别"。"单机 DuckDB + Olist、评测可复现、面试可当场演示"本身是**优势**，前提是 9 表星型模型真跑起来、而非 2 表。

**来源**：用户 2026-10-21 数据层复盘（"demo 味 / 高射炮打蚊子"）+ 代码核对（warehouse.py / lineage.py / detection 表引用统计：orders×6、dwd_orders×5、daily_metrics×4、dwd_order_items×1，其余 0）。

---

## 附：一句话速答卡片（面试前 30 分钟过一遍）

- **为什么 LangGraph**：状态机精确控流程 + checkpointer 支撑 HITL + state 做多 Agent 通信总线。
- **两种循环范式**：归因 = ReAct（工具循环，行动-观察）；整改 = Executor+Critic（生成→评审→重写，Reflexion）。
- **结构化输出**：`submit_diagnosis` 伪装工具 → Pydantic schema 强制；整改用 `tool_choice` 约束每轮输出格式。
- **防幻觉**：证据闸门 + evidence_chain 以真实调用为准（丢弃自述）。
- **安全**：SafeSQL 只读白名单，工具层断掉 DELETE。
- **评估**：ground-truth 对齐 + 复检口径 + 可逆/丢失分型；LLM-as-Judge 配人工校准。
- **数字**：F1=1.0 / 归因 0.75 / 整改 0.50（可逆 1.0 · 丢失 0.0）/ 端到端 0.50 / ~39s / ~78 万 token（真实 usage 计数）。
- **诚实边界**：数据丢失异常整改 0.0、血缘硬编码、案例库 4 条 demo——每个都能变成"我清楚这里为什么这样做、下一步怎么补"的加分叙事。
