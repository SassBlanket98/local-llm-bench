5. **Transcripts only contain grade lines for some tasks** (web_local-1.txt is 3 lines). Every task
   transcript must contain the full conversation. Add a registry in core (each `Chat` appends itself
   to a module-level list cleared by the runner before a task); the runner writes, per chat, every
   message (role, content, reasoning_content truncated to 4000 chars, tool_calls, tool results
   truncated to 2000 chars) followed by the Result notes/output.


## Interface (acceptance tests call exactly these)
- `llmbench.core.TASK_CHATS: list[Chat]` (every new `Chat` appends itself) and `llmbench.core.clear_task_chats() -> None`.
- `llmbench.core.format_task_transcript(result: Result) -> str`: every registered chat, each message under a header line `=== <role> ===`, then the Result notes and output.
