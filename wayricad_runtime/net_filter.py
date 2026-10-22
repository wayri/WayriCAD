"""Indexed, deterministic net-name search without creating net assignments."""
from __future__ import annotations

from collections import OrderedDict, defaultdict
from functools import lru_cache
import re


_FUZZY_MAX_QUERY = 96
_FUZZY_MAX_LABEL = 512
_FUZZY_RESULT_LIMIT = 100
_FUZZY_CANDIDATE_LIMIT = 512
_FUZZY_CELL_BUDGET = 25_000_000


@lru_cache(maxsize=128)
def _wildcard_regex(pattern: str):
    """Compile a tiny glob dialect where only * and ? are special.

    KiCad uses square brackets in bus names, so ``DATA[0]`` and ``DATA[*]``
    treat the brackets as ordinary characters; in the latter, ``*`` is still
    a wildcard.
    """
    expression = ''.join('.*' if char == '*' else '.' if char == '?'
                         else re.escape(char) for char in pattern)
    return re.compile(expression)


def _edit_distance_to_substring(query: str, text: str, limit: int):
    """Bounded Levenshtein distance from query to any substring in text.

    Dynamic programming allows free text before/after the match, so a typo in
    one net-path component can still find a long hierarchical net name. Work
    is bounded by ``len(query) * min(len(text), _FUZZY_MAX_LABEL)``.
    """
    width = len(query)
    if not width:
        return 0
    previous = list(range(width + 1))
    best = width + 1
    for char in text[:_FUZZY_MAX_LABEL]:
        current = [0] * (width + 1)
        for column in range(1, width + 1):
            current[column] = min(
                previous[column] + 1,
                current[column - 1] + 1,
                previous[column - 1] + (query[column - 1] != char),
            )
        if current[width] < best:
            best = current[width]
            if best == 0:
                return 0
        previous = current
    return best if best <= limit else None


class SearchIndex:
    """Cache case-folded names for repeatable literal, glob and fuzzy queries.

    Search defaults to a case-insensitive literal substring. ``*`` and ``?``
    opt into wildcard matching. Fuzzy matching is always opt-in via ``~text``
    or ``mode='fuzzy'`` and returns at most the best 100 ranked candidates.
    """
    def __init__(self, items):
        self.labels = tuple(str(item) for item in items)
        self.folded = tuple(item.casefold() for item in self.labels)
        self._gram_postings = {}

    def match(self, query, mode=None):
        text = str(query).strip()
        selected_mode = mode
        if selected_mode is None:
            if text.startswith('~'):
                selected_mode = 'fuzzy'
                text = text[1:].strip()
            elif '*' in text or '?' in text:
                selected_mode = 'wildcard'
            else:
                selected_mode = 'literal'
        elif selected_mode == 'fuzzy' and text.startswith('~'):
            text = text[1:].strip()
        if selected_mode not in ('literal', 'wildcard', 'fuzzy'):
            raise ValueError("mode must be 'literal', 'wildcard' or 'fuzzy'")

        folded_query = text.casefold()
        if not folded_query:
            return list(range(len(self.labels)))
        if selected_mode == 'literal':
            return [index for index, label in enumerate(self.folded)
                    if folded_query in label]
        if selected_mode == 'wildcard':
            pattern = _wildcard_regex(folded_query)
            return [index for index, label in enumerate(self.folded)
                    if pattern.search(label)]
        return self._fuzzy(folded_query)

    def _fuzzy(self, query):
        # Avoid noisy suggestions for very short input. Exact substring hits
        # still appear, even when fuzzy mode was explicitly requested.
        exact = [index for index, label in enumerate(self.folded) if query in label]
        if len(query) < 3 or len(query) > _FUZZY_MAX_QUERY:
            return exact[:_FUZZY_RESULT_LIMIT]

        # Allow a small, query-length-scaled edit budget: 1 for short queries,
        # 2 for medium and 3 for long queries. This rejects unrelated names.
        edit_limit = min(3, max(1, len(query) // 5))
        ranked = [(0, self.folded[index], self.labels[index], index)
                  for index in exact]
        exact_set = set(exact)
        candidates = self._fuzzy_candidates(query, edit_limit)
        cells = 0
        for index, _gram_score in candidates:
            label = self.folded[index]
            if index in exact_set or len(label) > _FUZZY_MAX_LABEL:
                continue
            cost = len(query) * len(label)
            if cells + cost > _FUZZY_CELL_BUDGET:
                break
            cells += cost
            distance = _edit_distance_to_substring(query, label, edit_limit)
            if distance is not None:
                ranked.append((distance, label, self.labels[index], index))
        ranked.sort()
        return [entry[3] for entry in ranked[:_FUZZY_RESULT_LIMIT]]

    def _fuzzy_candidates(self, query, edit_limit):
        """Use bounded q-gram overlap to rank/prune long-list fuzzy searches."""
        if len(query) < 4:
            return [(index, 0) for index in range(len(self.labels))]
        gram_size = 2 if len(query) < 8 else 3
        if gram_size not in self._gram_postings:
            postings = defaultdict(list)
            for index, label in enumerate(self.folded):
                if len(label) > _FUZZY_MAX_LABEL:
                    continue
                grams = {label[pos:pos + gram_size]
                         for pos in range(max(0, len(label) - gram_size + 1))}
                for gram in grams:
                    postings[gram].append(index)
            self._gram_postings[gram_size] = dict(postings)

        query_grams = {query[pos:pos + gram_size]
                       for pos in range(len(query) - gram_size + 1)}
        overlaps = defaultdict(int)
        for gram in query_grams:
            for index in self._gram_postings[gram_size].get(gram, ()):
                overlaps[index] += 1
        # One edit can disrupt at most gram_size+1 adjacent grams. The
        # conservative floor retains typo candidates without scanning every
        # long label when the list has thousands of unrelated names.
        minimum = max(1, len(query_grams) - (gram_size + 1) * edit_limit)
        candidates = [(index, count) for index, count in overlaps.items()
                      if count >= minimum]
        candidates.sort(key=lambda entry: (-entry[1], self.folded[entry[0]],
                                           self.labels[entry[0]], entry[0]))
        # Dense hierarchical inventories can share common path fragments and
        # leave nearly every label above the conservative q-gram floor. Score
        # only the best bounded candidate set with edit distance; overlap,
        # then stable label order, gives deterministic suggestions without
        # letting a typo query run DP across the entire inventory.
        return candidates[:_FUZZY_CANDIDATE_LIMIT]


_INDEX_CACHE = OrderedDict()
_INDEX_CACHE_SIZE = 8


def _search_index(names):
    labels = tuple(str(name) for name in names)
    index = _INDEX_CACHE.get(labels)
    if index is None:
        index = SearchIndex(labels)
        _INDEX_CACHE[labels] = index
        if len(_INDEX_CACHE) > _INDEX_CACHE_SIZE:
            _INDEX_CACHE.popitem(last=False)
    else:
        _INDEX_CACHE.move_to_end(labels)
    return index


def matching_nets(names, query, mode=None):
    """Return matching original net names in their original inventory order."""
    index = _search_index(names)
    return [index.labels[i] for i in index.match(query, mode=mode)]


def filter_combo(combo, names, query, mode=None):
    """Filter choices while keeping an existing selected net pinned.

    If the selected identity exists in the inventory but does not match the
    query, it remains as a visible choice at the top. The typed query never
    becomes a choice or assignment.
    """
    index = _search_index(names)
    chosen = combo.GetValue()
    visible = [index.labels[i] for i in index.match(query, mode=mode)]
    if chosen in index.labels and chosen not in visible:
        visible.insert(0, chosen)
    combo.Set(visible)
    if chosen in visible:
        combo.SetValue(chosen)
    else:
        combo.SetSelection(-1)
    return visible
