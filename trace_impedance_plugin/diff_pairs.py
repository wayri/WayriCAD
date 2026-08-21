"""Shared differential-pair net-name detection for KiWay tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence


@dataclass(frozen=True)
class DiffPair:
    rule: str
    positive: str
    negative: str


# Ordered most-specific first. Suffixes are matched case-insensitively.
_PAIR_RULES: Sequence[tuple[str, str, str]] = (
    ("_P/_N suffix", "_p", "_n"),
    ("_DP/_DN suffix", "_dp", "_dn"),
    ("_DP/_DM suffix", "_dp", "_dm"),
    ("+/- polarity", "+", "-"),
    ("_+/_- polarity", "_+", "_-"),
    ("P/N tail", "p", "n"),
)

_VOWELS = frozenset("aeiou")


def _strip_suffix(net: str, suffix: str) -> Optional[str]:
    if len(net) <= len(suffix) + 1:
        return None
    if not net.casefold().endswith(suffix):
        return None
    return net[: -len(suffix)]


def classify_pair(positive: str, negative: str) -> Optional[DiffPair]:
    """Return the rule linking two explicit net names, if any."""
    for rule, positive_suffix, negative_suffix in _PAIR_RULES:
        positive_base = _strip_suffix(positive, positive_suffix)
        negative_base = _strip_suffix(negative, negative_suffix)
        if positive_base is None or negative_base is None:
            continue
        if positive_base.casefold() != negative_base.casefold():
            continue
        if rule == "P/N tail":
            # Guard the loose tail rule: reject vowel-ending bases like
            # "CA" (CAP/CAN) while accepting route-style bases like "TX".
            if len(positive_base) < 2 or positive_base[-1].casefold() in _VOWELS:
                continue
        return DiffPair(rule=rule, positive=positive, negative=negative)
    return None


def find_mate(net: str, available: Iterable[str]) -> str:
    """Best mate candidate for ``net`` among ``available`` net names."""
    names = [value for value in available if value]
    lookup = {value.casefold(): value for value in names}
    for rule, positive_suffix, negative_suffix in _PAIR_RULES:
        base = _strip_suffix(net, positive_suffix)
        polarity = negative_suffix
        if base is None:
            base = _strip_suffix(net, negative_suffix)
            if base is None:
                continue
            polarity = positive_suffix
        if rule == "P/N tail" and (len(base) < 2 or base[-1].casefold() in _VOWELS):
            continue
        candidate = base + polarity
        hit = lookup.get(candidate.casefold())
        if hit:
            return hit
    return ""


def detect_pairs(net_names: Iterable[str]) -> List[DiffPair]:
    """Detect every differential pair present in ``net_names``."""
    names = sorted({value for value in net_names if value})
    taken: set[str] = set()
    pairs: List[DiffPair] = []
    for net in names:
        if net in taken:
            continue
        mate = find_mate(net, names)
        if not mate or mate == net:
            continue
        classified = classify_pair(net, mate)
        if classified is None:
            classified = classify_pair(mate, net)
        if classified is None:
            continue
        pairs.append(classified)
        taken.update({net, mate})
    return pairs


def pair_key(net: str) -> str:
    """Grouping key collapsing both legs onto their shared base name."""
    for _rule, positive_suffix, negative_suffix in _PAIR_RULES:
        base = _strip_suffix(net, positive_suffix)
        if base is not None:
            return base.casefold()
        base = _strip_suffix(net, negative_suffix)
        if base is not None:
            return base.casefold()
    return ""
