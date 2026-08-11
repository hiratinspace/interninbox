"""The first-run interactive wizard: location -> roles -> companies -> scan.

Pure question/answer logic with injectable input/print so tests script it.
It never touches the network or the filesystem itself — `cli.py` turns the
answers into an in-memory Config (same expansion path as a file config) and
handles the optional save.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from interninbox.registry import TIERS, estimate_label, select
from interninbox.roles import ROLE_PRESETS


@dataclass(frozen=True)
class WizardAnswers:
    locations: tuple[str, ...]
    roles: tuple[str, ...]
    tier: str  # a registry tier, or "config" for the user's own list


def run(
    *,
    input_fn: Callable[[str], str],
    print_fn: Callable[[str], None],
    config_companies: int,
) -> WizardAnswers:
    print_fn("interninbox — a few questions, then the scan. Blank = no preference.")

    raw = input_fn("Location (country, US state, or city — blank = anywhere): ").strip()
    locations = (raw,) if raw else ()

    names = sorted(ROLE_PRESETS)
    print_fn("Role types (numbers separated by spaces, blank = all):")
    for index, name in enumerate(names, start=1):
        print_fn(f"  [{index}] {name}")
    roles = _pick_many(input_fn("Roles: "), names)

    options: list[tuple[str, str]] = []  # (tier, menu line)
    if config_companies:
        options.append(("config", f"my config ({config_companies} boards)"))
    for tier in ("all", "top", "large", "startups"):
        count = len(select(tier))
        options.append((tier, f"{tier:<8} — {count} boards, {estimate_label(count)}"))
    print_fn("Companies:")
    start = 0 if config_companies else 1
    for index, (_, line) in enumerate(options, start=start):
        print_fn(f"  [{index}] {line}")
    tier = _pick_one(input_fn, print_fn, options, start=start)

    return WizardAnswers(locations=locations, roles=tuple(roles), tier=tier)


def _pick_many(raw: str, names: list[str]) -> list[str]:
    picked: list[str] = []
    for token in raw.split():
        if token.isdigit() and 1 <= int(token) <= len(names):
            name = names[int(token) - 1]
            if name not in picked:
                picked.append(name)
    return picked


def _pick_one(
    input_fn: Callable[[str], str],
    print_fn: Callable[[str], None],
    options: list[tuple[str, str]],
    *,
    start: int,
) -> str:
    while True:
        raw = input_fn("Companies: ").strip()
        if raw.isdigit() and start <= int(raw) < start + len(options):
            return options[int(raw) - start][0]
        print_fn(f"Pick a number between {start} and {start + len(options) - 1}.")


def render_config(answers: WizardAnswers) -> str:
    """A loadable interninbox.toml capturing the wizard's answers."""
    def toml_list(items: tuple[str, ...]) -> str:
        return "[" + ", ".join(f'"{item}"' for item in items) + "]"

    tier = answers.tier if answers.tier in TIERS else "none"
    return (
        "# Written by the interninbox wizard — edit freely; `interninbox scan`\n"
        "# uses it from now on (rerun the wizard any time with --interactive).\n"
        "companies = []\n"
        f'registry = "{tier}"\n'
        "\n"
        "[filters]\n"
        f"roles = {toml_list(answers.roles)}\n"
        f"locations = {toml_list(answers.locations)}\n"
    )
