import json

from src.main import main


def test_dry_run_end_to_end(tmp_path, capsys):
    code = main(
        [
            "--dry-run",
            "--state-path",
            str(tmp_path / "s.json"),
            "--output-dir",
            str(tmp_path / "out"),
            "--summary-json",
            str(tmp_path / "summary.json"),
        ]
    )
    assert code == 0
    summary = json.loads((tmp_path / "summary.json").read_text())
    assert summary["dry_run"] and summary["brief_items"] > 0 and summary["ok_sources"] >= 1
    assert (tmp_path / "out" / "latest_brief.md").exists()
    assert (tmp_path / "s.json").exists()
    # second run picks up state: items are no longer all NEW
    main(
        [
            "--dry-run",
            "--state-path",
            str(tmp_path / "s.json"),
            "--output-dir",
            str(tmp_path / "out"),
        ]
    )
    out = json.loads((tmp_path / "out" / "latest_brief.json").read_text())
    assert out["stats"]["new"] == 0


def test_every_preset_dry_runs(tmp_path):
    for preset in ("ai-tech-news", "kbeauty-commerce", "quant-macro"):
        code = main(
            [
                "--dry-run",
                "--preset",
                preset,
                "--state-path",
                str(tmp_path / f"{preset}.json"),
                "--output-dir",
                str(tmp_path / preset),
            ]
        )
        assert code == 0, preset


def test_bad_config_exit_code(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("sources: []\n", encoding="utf-8")
    assert main(["--config", str(bad), "--dry-run"]) == 3
