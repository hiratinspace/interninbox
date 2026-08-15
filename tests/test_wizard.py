"""Wizard flow with scripted answers, no TTY, no network."""

from interninbox import wizard
from interninbox.config import Filters
from interninbox.roles import ROLE_PRESETS


def _scripted(answers: list[str]):
    answers = list(answers)

    def input_fn(prompt: str) -> str:
        return answers.pop(0)

    return input_fn


def test_wizard_collects_location_roles_and_tier() -> None:
    lines: list[str] = []
    # location -> "California"; roles -> pick 1 and 3; companies -> option 2 (top)
    answers = wizard.run(
        input_fn=_scripted(["California", "1 3", "2", "", "y"]),
        print_fn=lines.append,
        config_companies=0,
    )
    role_names = sorted(ROLE_PRESETS)
    assert answers.locations == ("California",)
    assert answers.roles == (role_names[0], role_names[2])
    assert answers.tier == "top"
    assert answers.include_list is True  # blank accepts the default (yes)
    assert answers.require_sponsorship is True
    joined = "\n".join(lines)
    assert "~" in joined  # menu shows time estimates


def test_wizard_blank_answers_mean_everything() -> None:
    answers = wizard.run(
        input_fn=_scripted(["", "", "1", "", ""]),
        print_fn=lambda _: None,
        config_companies=0,
    )
    assert answers.locations == () and answers.roles == () and answers.tier == "all"
    assert answers.include_list is True and answers.require_sponsorship is False


def test_wizard_offers_my_config_option_when_config_exists() -> None:
    lines: list[str] = []
    answers = wizard.run(
        input_fn=_scripted(["", "", "0", "n", ""]),
        print_fn=lines.append,
        config_companies=3,
    )
    assert answers.tier == "config"
    assert any("my config" in line for line in lines)


def test_wizard_reprompts_on_bad_menu_choice() -> None:
    answers = wizard.run(
        input_fn=_scripted(["", "", "99", "2", "", ""]),  # invalid, then valid
        print_fn=lambda _: None,
        config_companies=0,
    )
    assert answers.tier == "top"


def test_render_config_is_loadable(tmp_path) -> None:
    from interninbox.config import load_config

    answers = wizard.WizardAnswers(
        locations=("California",),
        roles=("cybersecurity",),
        tier="top",
        include_list=True,
        require_sponsorship=True,
    )
    path = tmp_path / "interninbox.toml"
    path.write_text(wizard.render_config(answers), encoding="utf-8")
    config = load_config(path)
    assert config.registry == "top"
    assert config.sources == ("simplify",)
    assert config.filters.locations == ("California",)
    assert config.filters.roles == ("cybersecurity",)
    assert config.filters.require_sponsorship is True


def test_wizard_answers_flow_through_effective_filters() -> None:
    # Wizard answers ride the SAME expansion path as a file config: aliases
    # expand and role presets merge into match_keywords.
    from interninbox.cli import _effective_filters
    from interninbox.config import Config

    answers = wizard.WizardAnswers(
        locations=("CA",), roles=("software",), tier="top",
        include_list=False, require_sponsorship=False,
    )
    config = Config(
        companies=(),
        filters=Filters(locations=answers.locations, roles=answers.roles),
        registry=answers.tier,
    )
    filters = _effective_filters(config)
    assert "California" in filters.locations  # alias expansion applied
    assert "software" in filters.match_keywords  # role preset merged
