import pytest

from offerbench import config


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "test.db")
    yield


FAKE_PROVIDER = config.Provider(label="fake", base_url="https://fake.test/v1", api_key="k", model="fake-model")


@pytest.fixture(autouse=True)
def fake_llm_providers(monkeypatch):
    monkeypatch.setattr(config, "load_llm_providers", lambda: [FAKE_PROVIDER])
    yield
