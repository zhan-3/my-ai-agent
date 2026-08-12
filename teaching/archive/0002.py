from typing import TypedDict, Annotated, Literal                                                                                       
from langgraph.graph import StateGraph, START, END, add_messages                                                              
from langchain_core.messages import AnyMessage

class State(TypedDict):
    message: Annotated[list[AnyMessage], add_messages]# 消息自动追加
    city: str# 默认覆盖
    route: Literal["A", "B"]
    identified_city: str 

def identify(state):      # 节点：收 state，返回部分更新
    return {"identified_city": state["city"] + "→识别"}

def classify(state):
    return {"route": "A" if state["city"] == "北京" else "B"}    

def greetbeijing(state):
    return {"city": "北京欢迎你"}    

def greetother(state):
    return {"city": state["city"] + "向你问好"}  


graph = StateGraph(State)
graph.add_node("identify", identify)  # 第一个参数是字符串名称
graph.add_node("classify", classify)
graph.add_node("greetbeijing", greetbeijing)
graph.add_node("greetother", greetother)
graph.add_edge(START, "identify")
graph.add_edge("identify", "classify")
graph.add_conditional_edges(
    "classify",           # 源节点
    lambda state: state["route"],{
        "A": "greetbeijing",
        "B": "greetother"
    }
)
graph.add_edge("greetbeijing", END)
graph.add_edge("greetother", END)

app = graph.compile()
result = app.invoke({"message": [], "city": "北京", "route": ""})
print(result["city"])  