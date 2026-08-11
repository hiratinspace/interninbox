"""Config parsing: the happy path plus a friendly message for every error."""

from pathlib import Path

import pytest

from interninbox.config import ConfigError, load_config, parse_company


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "interninbox.toml"
    path.write_text(body, encoding="utf-8")
    return path


def test_full_config(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        """
        companies = ["greenhouse:stripe", "lever:plaid", "ashby:linear"]

        [filters]
        include_keywords = ["fellowship"]
        exclude_keywords = ["mechanical"]
        locations = ["New York"]
        remote_ok = false

        [usajobs]
        enabled = true
        email = "user@example.test"
        keywords = ["software", "data"]
        api_key_env = "MY_KEY"
        """,
    )
    config = load_config(path)
    assert [company.label for company in config.companies] == [
        "greenhouse:stripe",
        "lever:plaid",
        "ashby:linear",
    ]
    assert config.filters.include_keywords == ("fellowship",)
    assert config.filters.exclude_keywords == ("mechanical",)
    assert config.filters.locations == ("New York",)
    assert config.filters.remote_ok is False
    assert config.usajobs.enabled is True
    assert config.usajobs.email == "user@example.test"
    assert config.usajobs.keywords == ("software", "data")
    assert config.usajobs.api_key_env == "MY_KEY"


def test_minimal_config_defaults(tmp_path: Path) -> None:
    config = load_config(write(tmp_path, 'companies = ["greenhouse:stripe"]'))
    assert config.filters.remote_ok is True
    assert config.filters.locations == ()
    assert config.usajobs.enabled is False
    assert config.usajobs.api_key_env == "USAJOBS_API_KEY"


def test_missing_file_mentions_init(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="interninbox init"):
        load_config(tmp_path / "interninbox.toml")


def test_invalid_toml(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not valid TOML"):
        load_config(write(tmp_path, "companies = [unterminated"))


def test_missing_companies(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="nothing to scan"):
        load_config(write(tmp_path, "[filters]\nremote_ok = true"))


def test_empty_companies(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="nothing to scan"):
        load_config(write(tmp_path, "companies = []"))


def test_bad_shorthand() -> None:
    with pytest.raises(ConfigError, match='"ats:slug" form'):
        parse_company("stripejobs")
    with pytest.raises(ConfigError, match='"ats:slug" form'):
        parse_company("greenhouse:")


def test_unknown_ats_lists_supported() -> None:
    with pytest.raises(ConfigError, match="greenhouse, lever, ashby"):
        parse_company("taleo:megacorp")


def test_non_string_company_entry(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="must be strings"):
        load_config(write(tmp_path, "companies = [42]"))


def test_duplicate_company(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="duplicate"):
        load_config(write(tmp_path, 'companies = ["lever:plaid", "lever:plaid"]'))


def test_filters_wrong_types(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="filters.locations must be a list of strings"):
        load_config(write(tmp_path, 'companies = ["lever:plaid"]\n[filters]\nlocations = "NY"'))
    with pytest.raises(ConfigError, match="filters.remote_ok must be true or false"):
        load_config(
            write(tmp_path, 'companies = ["lever:plaid"]\n[filters]\nremote_ok = "yes"')
        )


def test_usajobs_enabled_requires_email(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="usajobs.email is not set"):
        load_config(write(tmp_path, 'companies = ["lever:plaid"]\n[usajobs]\nenabled = true'))


def test_match_keywords_parsed(tmp_path: Path) -> None:
    path = tmp_path / "interninbox.toml"
    path.write_text(
        'companies = ["greenhouse:stripe"]\n[filters]\nmatch_keywords = ["security"]\n',
        encoding="utf-8",
    )
    assert load_config(path).filters.match_keywords == ("security",)


def test_usajobs_only_config_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "interninbox.toml"
    path.write_text(
        '[usajobs]\nenabled = true\nemail = "fixture@example.test"\n', encoding="utf-8"
    )
    config = load_config(path)
    assert config.companies == ()
    assert config.usajobs.enabled


def test_nothing_to_scan_is_an_error(tmp_path: Path) -> None:
    path = tmp_path / "interninbox.toml"
    path.write_text("companies = []\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="nothing to scan"):
        load_config(path)
