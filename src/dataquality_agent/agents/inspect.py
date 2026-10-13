"""巡检 Agent（Planner + Executor）：调 M1 检测，产出结构化异常清单。

======== LangGraph 节点模型（核心心智模型）========

LangGraph 里每个节点是一个"纯函数"：输入 = 到目前为止的完整 state，
输出 = 只含它想改的字段的"部分更新字典"。合并和路由是 LangGraph 引擎做的，不是节点做的。

a) conn 闭包注入：
   make_inspect_node(conn) 是"返回函数的函数"（工厂）。它返回的 inspect 函数"记住了" conn
   （闭包），即使 make_inspect_node 已经 return 了，inspect 后面被调用时依然能访问 conn。
   为什么 conn 不走 state 传？因为 state 要能被序列化——LangGraph 要用 checkpointer 把 state
   存盘（HITL 暂停/恢复时）、在节点间传递，而 conn 是一个 DuckDB 活连接（文件句柄、锁、
   游标状态），没法序列化。
   原则：state 只放数据（可序列化：str/list/Pydantic 模型）；依赖（数据库连接、模型客户端、
   工具）一律走闭包注入。diagnose/remediate 里的 model、tools 也是同样的闭包注入。

b) state 来自哪里：
   state 是 LangGraph 引擎传进来的，不是手动构造的。graph.invoke(初始state, config) 时，
   引擎把"初始 state + 前面所有节点累计的更新"合并后的完整 state，作为参数传给当前节点。
   inspect 是入口节点（set_entry_point("inspect")），它前面没有别的节点，所以它拿到的 state
   就是你 invoke 时传进去的初始 state（比如 {"run_id": "r1"}）。
   注意：inspect 其实没读 state（它不需要 run_id），直接调 run_detection(conn) 干活——
   节点可以忽略输入。

c) return {"anomalies": report.anomalies} 返回什么？给谁？状态怎么更新？
   这不是返回完整 state，而是返回一个"部分更新字典"，语义是"把 state 的 anomalies 键
   更新成 report.anomalies 这个列表"。
   它返回给 LangGraph 引擎（不是直接给下一个节点）。引擎拿到返回值后做合并：
       new_state = {**old_state, **node_return}
   再把 new_state 传给下一个节点 diagnose。所以每个节点只返回自己负责的键
   （inspect 管 anomalies、diagnose 管 diagnoses、remediate 管 remediations...），互不干扰；
   state 随图流动逐步累积——这正是"Agent 间通过共享 state 通信"的机制（对应 AgentState）。

流程图：
   graph.invoke({"run_id":"r1"})
     └─ inspect(state={"run_id":"r1"})            → return {"anomalies":[A1]}
           merge → state={"run_id":"r1","anomalies":[A1]}
     └─ diagnose(state={... "anomalies":[A1]})    → return {"diagnoses":[D1]}
           merge → state={... "diagnoses":[D1]}
     └─ remediate(state={... diagnoses:[D1]})      → return {"remediations":[R1]}
           merge → ...（以此类推）

一句话收束：节点不是"调用下一个节点"，而是"交回部分更新 → 引擎合并 → 引擎交给下一个节点"。
"""
from dataquality_agent.detection.runner import run_detection


def make_inspect_node(conn):
    """返回巡检节点函数。conn 通过闭包注入（不放进 state——state 需可序列化）。"""
    def inspect(state):
        report = run_detection(conn)
        return {"anomalies": report.anomalies}
    return inspect
