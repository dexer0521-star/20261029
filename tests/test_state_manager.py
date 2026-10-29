from src.analyzers.schemas import DiffStatus, RawTrendItem
from src.config_loader import StateConfig
from src.storage.state_manager import StateManager


def _sm(tmp_path):
    sm = StateManager(StateConfig(rising_score_delta=10, rising_rank_jump=2), tmp_path / "s.json")
    sm.load()
    return sm


def test_first_run_all_new_and_persists(tmp_path, raw_items):
    sm = _sm(tmp_path)
    d = sm.diff(raw_items)
    assert {i.status for i in d} == {DiffStatus.NEW}
    assert [i.rank for i in d] == [1, 2, 3]
    sm.save(d, preset="t")
    assert (tmp_path / "s.json").exists()


def test_second_run_detects_rising_and_new(tmp_path, raw_items):
    sm = _sm(tmp_path)
    sm.save(sm.diff(raw_items), preset="t")
    nxt = [
        RawTrendItem(
            source="hackernews",
            title="LLM agents everywhere",
            url="https://a.com/1?utm_source=t",
            score=105,
        ),
        RawTrendItem(source="hackernews", title="Rust 2.0 released", url="https://a.com/2", score=90),
        RawTrendItem(source="y", title="LLM agents in Rust", url="https://a.com/3", score=95),
    ]
    sm2 = _sm(tmp_path)
    by_title = {i.title: i for i in sm2.diff(nxt)}
    assert by_title["LLM agents everywhere"].status == DiffStatus.STEADY
    assert by_title["LLM agents everywhere"].seen_runs == 2
    assert by_title["Rust 2.0 released"].status == DiffStatus.RISING
    assert by_title["Rust 2.0 released"].score_delta == 40
    assert by_title["LLM agents in Rust"].status == DiffStatus.NEW
    kws = sm2.rising_keywords(nxt)
    assert "llm" in kws and "rust" in kws


def test_corrupt_state_starts_fresh(tmp_path, raw_items):
    (tmp_path / "s.json").write_text("{not json", encoding="utf-8")
    sm = _sm(tmp_path)
    assert sm.state.items == {}
    assert all(i.status == DiffStatus.NEW for i in sm.diff(raw_items))
