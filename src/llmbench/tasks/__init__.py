from llmbench.tasks import (
    t1_tools,
    t2_extract,
    t3_logs,
    t4_bugfix,
    t5_bash,
    t6_context,
    t7_commit,
    t8_toolcall,
    t9_agent_repo,
    t10_docqa,
    t11_summary,
    t12_web_local,
    t13_web_live,
    t14_ifeval,
)

TASKS = [
    t1_tools,
    t2_extract,
    t3_logs,
    t4_bugfix,
    t5_bash,
    t6_context,
    t7_commit,
    t8_toolcall,
    t9_agent_repo,
    t10_docqa,
    t11_summary,
    t12_web_local,
    t13_web_live,
    t14_ifeval,
]

CATEGORY_WEIGHTS = {
    "agentic": 25,
    "tool_calling": 20,
    "coding_loop": 15,
    "docs": 15,
    "web": 7,
    "web_live": 3,
    "instruction_following": 10,
    "single_shot": 5,
}
