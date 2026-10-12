"""Read the previous turn out of Hermes's OpenAI-format conversation history."""

TEXT_PARTS = {"text", "output_text", "input_text"}


def text_of(message: dict) -> str:
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and part.get("type") in TEXT_PARTS)
    return ""


def previous_turn(messages: list[dict]) -> tuple[str, str]:
    """(user_text, assistant_text) for the last turn that has an assistant reply.

    pre_llm_call receives the history with the new prompt already at the end, so
    the walk first skips back to the newest assistant message. One turn spans
    every assistant message after its user message; tool messages sit between
    them and carry no prose.
    """
    end = len(messages) - 1
    while end >= 0 and messages[end].get("role") != "assistant":
        end -= 1
    if end < 0:
        return "", ""
    start = end
    while start >= 0 and messages[start].get("role") != "user":
        start -= 1
    user_text = text_of(messages[start]) if start >= 0 else ""
    replies = [text_of(m).strip() for m in messages[start + 1:end + 1] if m.get("role") == "assistant"]
    return user_text, "\n\n".join(r for r in replies if r)
