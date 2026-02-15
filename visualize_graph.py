from langgraph.prebuilt import create_react_agent
from uyuni_ai_agent.llm_provider import get_llm
from uyuni_ai_agent.react_agent import ALL_TOOLS

llm = get_llm()
agent = create_react_agent(llm, ALL_TOOLS)

# Option 1: ASCII art in terminal (no extra deps)
agent.get_graph().print_ascii()

# Option 2: Mermaid syntax — copy-paste to https://mermaid.live
print("\n\n--- Mermaid Diagram (paste at https://mermaid.live) ---\n")
print(agent.get_graph().draw_mermaid())