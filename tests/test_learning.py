import time

import requests

from jarvis.learning import Learner, _parse_facts
from jarvis.memory import Memory


def test_parse_facts_tolerates_prose():
    assert _parse_facts('はい。["Aが好き", "Bに住んでいる"] 以上') == ["Aが好き", "Bに住んでいる"]
    assert _parse_facts("[]") == []
    assert _parse_facts("nothing here") == []
    assert _parse_facts('[{"fact": "x" * 1}]') == []  # too short


def test_reflect_adds_new_facts_and_dedupes(config):
    memory = Memory(config.data_dir)
    memory.append_turn("user", "ぼくはゆうき。コーヒーが好きなんだ")
    memory.append_turn("assistant", "いいね！")
    memory.remember("コーヒーが好き")
    learner = Learner(config, memory)
    added = learner.reflect()
    assert added == ["ユーザーの名前はゆうき"]
    facts = memory.load_facts()
    assert [f["fact"] for f in facts] == ["コーヒーが好き", "ユーザーの名前はゆうき"]
    assert facts[-1]["source"] == "auto"
    # Second pass finds nothing new.
    assert learner.reflect() == []


def test_summarise_folds_old_history(config):
    memory = Memory(config.data_dir, history_turns=4, summary_after=6)
    for i in range(10):
        memory.append_turn("user", f"message {i}")
    learner = Learner(config, memory)
    summary = learner.summarise()
    assert "要約" in summary
    assert memory.load_summary() == summary
    assert [r["text"] for r in memory.recent_rows(100)] == ["message 6", "message 7", "message 8", "message 9"]
    # The summary is now part of the prompt.
    from jarvis.persona import build_system_prompt

    assert summary in build_system_prompt(config, "", memory.load_summary())


def test_learning_runs_after_turns_via_web(config):
    from tests.test_web_and_agent import Server, _sse

    config.reflect_every = 1
    srv = Server(config)
    try:
        r = requests.post(srv.url + "/api/chat", json={"message": "ぼくはゆうき、コーヒーが好き"}, stream=True)
        _sse(r)
        deadline = time.time() + 10
        while time.time() < deadline:
            facts = requests.get(srv.url + "/api/memory").json()["facts"]
            if facts:
                break
            time.sleep(0.1)
        assert any("ゆうき" in f["fact"] for f in facts)
        state = requests.get(srv.url + "/api/state").json()
        assert state["learning"]["job"] == "reflect"
    finally:
        srv.close()


def test_cancel_endpoint(config):
    from tests.test_web_and_agent import Server

    srv = Server(config)
    try:
        assert requests.post(srv.url + "/api/chat/cancel").json()["ok"] is False  # nothing running
    finally:
        srv.close()


def test_groq_preset(monkeypatch, tmp_path):
    for k in ("JARVIS_OPENAI_BASE_URL", "JARVIS_OPENAI_MODEL", "JARVIS_OPENAI_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("JARVIS_PROVIDER", "groq")
    monkeypatch.setenv("JARVIS_GROQ_API_KEY", "gsk_test")
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    from jarvis.config import Config

    c = Config.load()
    assert c.is_openai_compat and c.is_local and c.is_cloud
    assert c.openai_base_url == "https://api.groq.com/openai/v1"
    assert c.openai_model == "llama-3.3-70b-versatile"
    assert c.openai_api_key == "gsk_test"
    assert c.learn_idle_seconds == 5


def test_groq_without_key_explains(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_PROVIDER", "groq")
    monkeypatch.delenv("JARVIS_GROQ_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.setenv("JARVIS_DATA_DIR", str(tmp_path))
    from jarvis.config import Config
    from jarvis.web.server import JarvisWeb

    app = JarvisWeb(Config.load())
    assert app.ensure_assistant() is None
    assert "API キー" in app.backend_error
    app.scheduler.stop()
