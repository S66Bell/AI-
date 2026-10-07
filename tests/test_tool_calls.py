from jarvis.backends.tool_calls import extract_text_tool_calls, parse_arguments


def test_parse_arguments_accepts_dict_and_json():
    assert parse_arguments({"a": 1}) == {"a": 1}
    assert parse_arguments('{"query": "x"}') == {"query": "x"}
    assert parse_arguments("") == {}
    assert parse_arguments(None) == {}


def test_parse_arguments_repairs_common_mistakes():
    assert parse_arguments('{"a": 1,}') == {"a": 1}
    assert parse_arguments("{'a': True}") == {"a": True}
    assert parse_arguments('{"a": "b"') == {"a": "b"}
    assert parse_arguments('```json\n{"a": 2}\n```') == {"a": 2}
    assert parse_arguments("not json at all") == {}


def test_extract_tagged_tool_call():
    text, calls = extract_text_tool_calls(
        'Let me check. <tool_call>{"name": "web_search", "arguments": {"query": "jarvis"}}</tool_call>',
        {"web_search"},
    )
    assert text == "Let me check."
    assert len(calls) == 1
    assert calls[0]["function"] == {"name": "web_search", "arguments": {"query": "jarvis"}}
    assert calls[0]["id"].startswith("call_")


def test_extract_ignores_unknown_tools_and_plain_json():
    text, calls = extract_text_tool_calls('{"name": "nope", "arguments": {}}', {"web_search"})
    assert calls == [] and text.startswith("{")
    text, calls = extract_text_tool_calls('Here is JSON: {"x": 1}', {"web_search"})
    assert calls == []


def test_extract_bare_json_call():
    text, calls = extract_text_tool_calls('{"name": "run_shell", "parameters": {"command": "ls"}}', {"run_shell"})
    assert text == ""
    assert calls[0]["function"]["arguments"] == {"command": "ls"}
