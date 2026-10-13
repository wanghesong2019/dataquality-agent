from dataquality_agent.config import Settings


def test_settings_defaults():
    s = Settings()
    assert s.db_path.endswith(".duckdb")
    assert s.seed == 42


def test_settings_override():
    s = Settings(data_dir="/tmp/x")
    assert s.data_dir == "/tmp/x"
