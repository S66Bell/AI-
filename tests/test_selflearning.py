import time

import requests

from jarvis.knowledge import Knowledge, chunk_text, similarity


def test_knowledge_search_japanese(tmp_path):
    kb = Knowledge(tmp_path)
    kb.add("社内ルール", "有給休暇の申請は前日までに人事ポータルから行う。\n\n会議室の予約は共有カレンダーで行う。")
    kb.add("レシピ", "カレーの作り方: 玉ねぎを飴色になるまで炒め、肉と野菜を加えて煮込む。")
    hits = kb.search("有給の申請はどうする?")
    assert hits and "人事ポータル" in hits[0]["text"]
    assert kb.search("宇宙船の操縦方法") == []
    ctx = kb.context_for("カレーの作り方")
    assert "玉ねぎ" in ctx and "(レシピ)" in ctx
    assert len(kb) == 2 and kb.remove(kb.list()[0]["id"]) and len(kb) == 1
    assert Knowledge(tmp_path).search("有給")  # persisted


def test_chunking_and_similarity():
    chunks = chunk_text("\n\n".join("段落%d " % i * 40 for i in range(10)), size=300)
    assert all(len(c) <= 450 for c in chunks) and len(chunks) >= 3
    assert similarity("今週のAIニュースを調べる", "AIのニュースを調べて") > similarity("今週のAIニュースを調べる", "カレーを作る")


def test_reflection_extracts_lessons(config):
    from jarvis.learning import Learner
    from jarvis.memory import Memory

    memory = Memory(config.data_dir)
    memory.append_turn("user", "もっと短く答えて")
    memory.append_turn("assistant", "了解!")
    Learner(config, memory).reflect()
    assert [l["text"] for l in memory.load_lessons()] == ["返事は短くする"]
    # Lessons reach the system prompt.
    from jarvis.persona import build_system_prompt

    assert "返事は短くする" in build_system_prompt(config, "", "", memory.lessons_as_text())


def test_feedback_creates_lesson_and_knowledge_api(config):
    from tests.test_web_and_agent import Server

    config.reflect_every = 100
    srv = Server(config)
    try:
        r = requests.post(srv.url + "/api/feedback", json={"rating": "down", "note": "長すぎ", "user": "天気は?", "reply": "……"}).json()
        assert r["learning"] is True
        deadline = time.time() + 10
        while time.time() < deadline:
            lessons = requests.get(srv.url + "/api/memory").json()["lessons"]
            if lessons:
                break
            time.sleep(0.1)
        assert lessons and "結論を先に" in lessons[0]["text"]
        assert requests.post(srv.url + "/api/lessons/forget", json={"query": "結論"}).json()["removed"] == 1

        r = requests.post(srv.url + "/api/knowledge", json={"title": "メモ", "text": "合言葉はひまわり。"}).json()
        assert r["ok"]
        mem = requests.get(srv.url + "/api/memory").json()
        assert mem["knowledge"][0]["title"] == "メモ"
        # The chat gets the snippet appended.
        resp = requests.post(srv.url + "/api/chat", json={"message": "合言葉は何だっけ?"}, stream=True)
        list(resp.iter_lines())
        assert srv.app.assistant.backend.messages[-2]["content"].count("ひまわり") >= 1
        kid = mem["knowledge"][0]["id"]
        assert requests.delete(srv.url + f"/api/knowledge/{kid}").json()["ok"]
    finally:
        srv.close()


def test_task_reflection_writes_playbook(config):
    from tests.test_web_and_agent import Server

    srv = Server(config)
    try:
        requests.post(srv.url + "/api/tasks", json={"goal": "find something"})
        deadline = time.time() + 15
        while time.time() < deadline:
            pb = requests.get(srv.url + "/api/memory").json()["playbook"]
            if pb:
                break
            time.sleep(0.1)
        assert pb and "web_search" in pb[0]["lesson"]
        assert "web_search" in srv.app.memory.playbook_for("find something else")
    finally:
        srv.close()
