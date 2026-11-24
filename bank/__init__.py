"""Local interview bank. Public and student-specific cards share the same format."""

import json
import re
import unicodedata
from copy import deepcopy
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def _read(filename):
    return json.loads(Path(__file__).with_name(filename).read_text(encoding="utf-8"))


def list_cards():
    files = (
        "cards.json",
        "foundations.json",
        "legacy.json",
        "special_cases.json",
        "supplement_a.json",
        "supplement_b.json",
        "supplement_c.json",
    )
    return [deepcopy(card) for filename in files for card in _read(filename)]


def taxonomy():
    return deepcopy(_read("taxonomy.json"))


def migration_ledger():
    return deepcopy(_read("migration.json"))


def _normalized(text):
    return "".join(unicodedata.normalize("NFKC", text).casefold().split())


@lru_cache(maxsize=1)
def _aliases():
    result = {}
    for term, variants in _read("taxonomy.json")["aliases"].items():
        group = frozenset(_normalized(value) for value in [term, *variants])
        result.update((value, group) for value in group)
    return result


@lru_cache(maxsize=1)
def _old_ids():
    result = {}
    for row in _read("migration.json"):
        for key in (row["legacy_id"], f"旧题{row['number']}", f"#{row['number']}"):
            result[_normalized(key)] = row
    return result


def lookup_legacy(query):
    return deepcopy(_old_ids().get(_normalized(query)))


def search_cards(query="", stage="", topic="", subtopic="", cards=None):
    """Match all requested terms, expanding aliases inside a single topic path."""
    needle = _normalized(query)
    aliases = _aliases()
    groups = (
        [aliases[needle]]
        if needle in aliases
        else [
            aliases.get(term, {term})
            for raw in re.split(r"[\s→/]+", query)
            if (term := _normalized(raw))
        ]
    )
    legacy = _old_ids().get(needle) if needle else None
    if legacy and not legacy["card_id"]:
        return []
    results = []
    for card in list_cards() if cards is None else cards:
        if stage and card.get("stage") != stage:
            continue
        paths = [(card.get("topic", ""), card.get("subtopic", ""))]
        paths.extend(
            (pair["topic"], pair["subtopic"]) for pair in card.get("related", [])
        )
        if not any(
            (not topic or t == topic) and (not subtopic or s == subtopic)
            for t, s in paths
        ):
            continue
        if legacy and card["id"] != legacy["card_id"]:
            continue
        if groups and not legacy:
            fields = [
                card.get(key, "")
                for key in ("id", "title", "prompt", "stage", "spoken", "followup")
            ]
            fields.extend(card.get("tags", []))
            fields.extend(card.get("also_asked", []))
            fields.extend(value for path in paths for value in path)
            haystack = _normalized(" ".join(fields))
            if not all(any(word in haystack for word in group) for group in groups):
                continue
        results.append({**card, "legacy_status": legacy["status"]} if legacy else card)
    return results
