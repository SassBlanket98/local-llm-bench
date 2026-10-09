from llmbench import core
from llmbench.core import Chat, Result, clear_task_chats, format_task_transcript


def test_chats_register_and_clear():
    clear_task_chats()
    a, b = Chat("m"), Chat("m")
    assert core.TASK_CHATS == [a, b]
    clear_task_chats()
    assert core.TASK_CHATS == []


def test_transcript_has_every_chat_message_and_result():
    clear_task_chats()
    c1 = Chat("m")
    c1.messages.append({"role": "user", "content": "first question"})
    c1.messages.append({"role": "assistant", "content": "first answer"})
    c2 = Chat("m")
    c2.messages.append({"role": "user", "content": "second question"})
    c2.messages.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "type": "function",
                    "function": {"name": "fetch_url", "arguments": '{"url": "/x"}'},
                }
            ],
        }
    )
    c2.messages.append({"role": "tool", "content": "R" * 5000})
    text = format_task_transcript(Result(True, 1.0, "grade notes here", "final output here"))
    for s in (
        "=== user ===",
        "=== assistant ===",
        "first question",
        "first answer",
        "second question",
        "fetch_url",
        "grade notes here",
        "final output here",
    ):
        assert s in text, s
    assert "R" * 2000 in text
    assert "R" * 2500 not in text


def test_reasoning_truncated():
    clear_task_chats()
    c = Chat("m")
    c.messages.append({"role": "assistant", "content": "ok", "reasoning_content": "Z" * 9000})
    text = format_task_transcript(Result(True, 1.0, "n", "o"))
    assert "Z" * 4000 in text and "Z" * 4500 not in text
