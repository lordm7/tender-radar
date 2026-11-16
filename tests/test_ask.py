"""Ask the booklet: page selection, citation checks, storage, web and CLI."""

from pathlib import Path

from fastapi.testclient import TestClient

from tender_radar.ai.provider import AIError, FakeProvider
from tender_radar.db import init_db, make_engine, session_scope
from tender_radar.models import BookletAnswer, BookletBrief
from tender_radar.reader.ask import answer_question, build_ask_prompt, select_pages
from tender_radar.repository import get_pages, latest_brief_id, list_answers, save_answer, save_brief

SAMPLE = Path(__file__).resolve().parents[1] / "data" / "seed" / "sample_booklet.pdf"

PAGES = [
    "المقدمة: ترغب الأمانة في تطوير منصة رقمية لإدارة المواعيد.",
    "نطاق العمل: تطوير بوابة ويب وتطبيق جوال.",
    "شروط التأهيل: الحصول على شهادة ISO 27001 سارية المفعول.",
    "الغرامات: غرامة تأخير بنسبة 1% عن كل أسبوع بحد أقصى 10%.",
]


# --- page selection -------------------------------------------------------

def test_short_booklet_sends_every_page():
    assert select_pages("ما هي غرامة التأخير؟", PAGES, budget_chars=10_000) == [1, 2, 3, 4]


def test_long_booklet_sends_the_most_relevant_pages_in_page_order():
    pages = PAGES + ["حشو " * 200] * 6  # long filler pages that match nothing
    chosen = select_pages("ما هي غرامة التأخير؟", pages, budget_chars=250)
    assert 4 in chosen  # the penalties page is picked first
    assert all(n <= 4 for n in chosen)  # no long filler page fits after it
    assert chosen == sorted(chosen)
    assert sum(len(pages[n - 1]) for n in chosen) <= 250


def test_best_page_is_kept_even_when_the_budget_is_tiny():
    pages = ["حشو " * 100, "حشو " * 100, "غرامة تأخير " * 50]
    assert select_pages("غرامة التأخير", pages, budget_chars=10) == [3]


def test_matching_ignores_arabic_spelling_variants():
    pages = ["حشو " * 100, "الغرامه: غرامة تأخير", "حشو " * 100]
    assert select_pages("غرامه التاخير", pages, budget_chars=60)[0] == 2


def test_no_keyword_hit_falls_back_to_the_first_pages():
    pages = ["صفحة أولى " * 20, "صفحة ثانية " * 20, "صفحة ثالثة " * 20]
    assert select_pages("What is the penalty?", pages, budget_chars=250) == [1]


# --- answering ------------------------------------------------------------

def test_prompt_marks_pages_with_their_real_numbers():
    prompt = build_ask_prompt("سؤال؟", PAGES, [2, 4])
    assert "[page 2]" in prompt and "[page 4]" in prompt
    assert "[page 1]" not in prompt
    assert "سؤال؟" in prompt


def test_answer_keeps_only_citations_of_pages_the_ai_saw():
    fake = FakeProvider([{"answer": "1% أسبوعيا بحد أقصى 10%", "citations": [4, 9], "found": True}])
    answer = answer_question("ما هي غرامة التأخير؟", PAGES, fake)
    assert answer.citations == [4]  # page 9 does not exist: dropped, never shown
    assert answer.found


def test_found_answer_without_a_valid_citation_is_not_trusted():
    fake = FakeProvider([{"answer": "شيء ما", "citations": [42], "found": True}])
    answer = answer_question("سؤال", PAGES, fake)
    assert answer.citations == []
    assert answer.found is False


def test_empty_question_never_calls_the_ai():
    fake = FakeProvider()
    answer = answer_question("   ", PAGES, fake)
    assert fake.calls == []
    assert answer.found is False


# --- storage --------------------------------------------------------------

def test_pages_and_answers_are_stored_with_the_brief(engine):
    with session_scope(engine) as s:
        brief_id = save_brief(s, "b.pdf", BookletBrief(scope="x"), pages=PAGES)
        save_answer(s, brief_id, "سؤال؟", BookletAnswer(answer="جواب", citations=[2]))
    with session_scope(engine) as s:
        assert get_pages(s, brief_id) == PAGES
        qa = list_answers(s, brief_id)
        assert [(q, a.answer, a.citations) for q, a in qa] == [("سؤال؟", "جواب", [2])]
        assert latest_brief_id(s, "b.pdf") == brief_id


def test_brief_saved_without_pages_has_none(engine):
    with session_scope(engine) as s:
        brief_id = save_brief(s, "b.pdf", BookletBrief(scope="x"))
    with session_scope(engine) as s:
        assert get_pages(s, brief_id) is None


# --- web ------------------------------------------------------------------

def _app_with_brief(tmp_path, answers):
    from tender_radar.settings import Settings
    from tender_radar.web.app import create_app

    settings = Settings(database_url=f"sqlite:///{(tmp_path / 'a.db').as_posix()}", ai_provider="fake")
    engine = make_engine(settings.database_url)
    init_db(engine)
    with session_scope(engine) as s:
        brief_id = save_brief(s, "b.pdf", BookletBrief(scope="نطاق"), pages=PAGES)
    engine.dispose()
    return create_app(settings, provider=FakeProvider(answers)), brief_id


def test_web_ask_shows_answer_with_page_citation(tmp_path):
    app, brief_id = _app_with_brief(tmp_path, [{"answer": "بحد أقصى 10%", "citations": [4], "found": True}])
    client = TestClient(app)
    assert "Ask the booklet" in client.get(f"/briefs/{brief_id}").text
    r = client.post(f"/briefs/{brief_id}/ask", data={"question": "ما هي غرامة التأخير؟"})
    assert r.status_code == 200
    assert "بحد أقصى 10%" in r.text
    assert "ما هي غرامة التأخير؟" in r.text
    assert "p. 4" in r.text


def test_web_ask_reports_ai_failure_without_crashing(tmp_path):
    app, brief_id = _app_with_brief(tmp_path, [AIError("down")])
    r = TestClient(app).post(f"/briefs/{brief_id}/ask", data={"question": "سؤال؟"})
    assert r.status_code == 502
    assert "try again" in r.text


def test_read_only_brief_shows_answers_but_no_form(tmp_path):
    from tender_radar.web.app import render_brief

    qa = [("سؤال؟", BookletAnswer(answer="جواب", citations=[3]))]
    html = render_brief(BookletBrief(scope="x"), "b.pdf", read_only=True, qa=qa, brief_id=1)
    assert "جواب" in html and "p. 3" in html
    assert "<form" not in html


# --- CLI ------------------------------------------------------------------

def test_cli_ask_answers_and_stores_on_the_latest_brief(tmp_path, monkeypatch, capsys):
    from tender_radar import __main__ as cli

    monkeypatch.setenv("TR_DATABASE_URL", f"sqlite:///{(tmp_path / 'c.db').as_posix()}")
    assert cli.main(["seed"]) == 0
    assert cli.main(["brief", str(SAMPLE), "--profile", "najd-digital"]) == 0
    fake = FakeProvider([{"answer": "ISO 27001 مطلوبة", "citations": [3], "found": True}])
    monkeypatch.setattr(cli, "get_provider", lambda settings: fake)
    assert cli.main(["ask", str(SAMPLE), "هل تشترط شهادة ISO 27001؟"]) == 0
    out = capsys.readouterr().out
    assert "ISO 27001 مطلوبة" in out and "p. 3" in out
    engine = make_engine(f"sqlite:///{(tmp_path / 'c.db').as_posix()}")
    with session_scope(engine) as s:
        assert len(list_answers(s, latest_brief_id(s, SAMPLE.name))) == 1
    engine.dispose()
