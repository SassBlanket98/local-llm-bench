from llmbench.core import Chat, Result, clear_task_chats, format_task_transcript


def test_format_task_transcript_includes_messages():
    clear_task_chats()
    chat = Chat("m")
    chat.messages.append({"role": "user", "content": "hello"})
    chat.messages.append({"role": "assistant", "content": "world"})
    r = Result(True, 1.0, "ok", "grade line")
    text = format_task_transcript(r)
    assert "=== user ===" in text
    assert "hello" in text
    assert "=== assistant ===" in text
    assert "grade line" in text
