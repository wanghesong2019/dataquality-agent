from dataquality_agent.cli import main


def test_init_and_detect(tmp_path, capsys):
    d = str(tmp_path)
    # init 生成样本数据 + 本地配置
    assert main(["init", "--dir", d]) == 0
    # 幂等：再次 init 不覆盖、不报错
    assert main(["init", "--dir", d]) == 0
    assert (tmp_path / "data" / "olist_orders_dataset.csv").exists()
    assert (tmp_path / ".env").exists()

    # detect 无 key 跑通
    assert main(["detect", "--dir", d]) == 0
    out = capsys.readouterr().out
    assert "异常" in out


def test_detect_no_data(tmp_path, capsys):
    assert main(["detect", "--dir", str(tmp_path)]) == 1  # 非零
    assert "init" in capsys.readouterr().err  # 提示先 init


def test_eval_runs_deterministic_eval(tmp_path, capsys):
    d = str(tmp_path)
    assert main(["init", "--dir", d]) == 0
    assert main(["eval", "--dir", d]) == 0
    out = capsys.readouterr().out
    assert "F1=" in out          # 真实输出 F1，而非空壳
    assert "待实现" not in out


def test_detect_passes_assertions_path(tmp_path, monkeypatch):
    d = str(tmp_path)
    assert main(["init", "--dir", d]) == 0
    yaml = tmp_path / "assertions.yaml"
    yaml.write_text("assertions:\n  - {name: x, type: not_null, table: orders, column: customer_id}\n",
                    encoding="utf-8")

    import dataquality_agent.detection.runner as runner
    captured = {}

    def fake(adapter, **kwargs):
        captured["assertions_path"] = kwargs.get("assertions_path")
        return runner.DetectionReport()

    monkeypatch.setattr(runner, "run_detection", fake)
    assert main(["detect", "--dir", d, "--assertions", str(yaml)]) == 0
    assert captured["assertions_path"] == str(yaml)
