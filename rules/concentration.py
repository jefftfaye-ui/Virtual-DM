"""Concentration helpers. The DC math lives in rules/damage; this is for the state verbs."""

from __future__ import annotations


def start(char: dict, spell_or_effect: str) -> dict:
    char["concentrating_on"] = spell_or_effect
    return char


def end(char: dict) -> dict:
    char["concentrating_on"] = None
    return char


def is_concentrating(char: dict) -> bool:
    return bool(char.get("concentrating_on"))
