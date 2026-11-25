"""Discovery Mode: re-ranking of personalised recommendation candidates.

Discovery Mode lets the user choose how adventurous the recommendations are (Safe,
Balanced, Adventurous). It is NOT a separate model: the item-based CF model first
produces a ranked candidate list (its top ``CANDIDATE_POOL`` movies for the user), and
this module re-orders those candidates. Every recommended movie therefore still comes
from the user's personalised candidates; the mode only decides how much the final list
trades relevance for exploration.

Greedy re-ranking (in the spirit of Maximal Marginal Relevance, Carbonell and Goldstein,
1998, and of the topic diversification of Ziegler et al., 2005). The list is built one
position at a time; at each step the remaining candidate with the highest value is
chosen::

    value(i) = (1 - w) * relevance(i) + w * (NOVELTY_SHARE * novelty(i)
                                             + (1 - NOVELTY_SHARE) * diversity(i | chosen))

All three factors are in [0, 1] and are computed from data the project already has:

* ``relevance`` - position of the movie in the CF candidate ranking, rescaled to [0, 1]
  (1 = best candidate, 0 = last). The position is used instead of the raw score because
  ``weighted_sum`` scores are not on a fixed scale (they grow with the number of rated
  neighbours and differ from user to user).
* ``novelty`` - popularity-based self-information ``-log2(p(i))`` with ``p(i)`` the share
  of training ratings of the movie (Zhou et al., 2010; Kaminskas and Bridge, 2016),
  min-max rescaled within the candidate pool. Rarely rated movies are more novel. The
  rating counts come from the popularity baseline file (``rating_count``).
* ``diversity`` - ``1 - max Jaccard(genres(i), genres(j))`` over the movies ``j`` already
  chosen: a candidate that shares no genre with the list so far adds the most variety
  (genre-based intra-list distance, Ziegler et al., 2005; Kaminskas and Bridge, 2016).
  It is 1 for the first position, where nothing has been chosen yet.

``w`` is the exploration weight of the mode (``DISCOVERY_WEIGHTS``). With ``w = 0`` the
original CF order is returned unchanged. Ties keep the original CF order.

The weights are design parameters fixed before any measurement; they were not tuned on
any dataset. Their justification is in the Phase 7.4 report
(frontend/docs/phase_7_4_recommendations_discovery_mode_implementation.md).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence

import numpy as np

# Exploration weight w of each mode: the share of the value that goes to novelty and
# diversity instead of relevance.
DISCOVERY_WEIGHTS = {"safe": 0.15, "balanced": 0.35, "adventurous": 0.6}
DEFAULT_MODE = "balanced"

# Number of CF candidates that are re-ranked. It bounds how far from the user's top
# recommendations a mode can go (the API returns at most 20 movies, so 5x that).
CANDIDATE_POOL = 100

# Novelty and diversity share the exploration weight equally: there is no evidence in
# this project to favour one of them.
NOVELTY_SHARE = 0.5


def rerank(
    candidates: Sequence[tuple[int, float]],
    n: int,
    mode: str,
    genres: Mapping[int, Iterable[str]],
    rating_counts: Mapping[int, int],
) -> list[tuple[int, float]]:
    """Re-order ranked ``(movieId, score)`` candidates for a Discovery Mode; return the top ``n``.

    * ``candidates`` must be best first (the CF output). Repeated movieIds keep their
      first position only.
    * ``genres`` maps movieId -> genre names; a movie without genres counts as sharing
      nothing with the others.
    * ``rating_counts`` maps movieId -> number of training ratings (popularity baseline).
    * The returned pairs keep the ORIGINAL model score, so the score stays a ranking
      signal of the model; only the order changes.
    * Fewer than ``n`` candidates simply give a shorter list.

    Raises ValueError for an unknown mode or a non-positive ``n``.
    """
    if mode not in DISCOVERY_WEIGHTS:
        raise ValueError(f"unknown Discovery Mode {mode!r}; expected one of {sorted(DISCOVERY_WEIGHTS)}")
    if isinstance(n, bool) or not isinstance(n, int) or n < 1:
        raise ValueError(f"n must be a positive integer, got {n!r}")

    first_scores: dict[int, float] = {}
    for movie_id, score in candidates:
        first_scores.setdefault(int(movie_id), float(score))
    unique = list(first_scores.items())
    if not unique:
        return []
    movie_ids = [movie_id for movie_id, _ in unique]
    size = len(movie_ids)
    weight = DISCOVERY_WEIGHTS[mode]

    relevance = 1.0 - np.arange(size) / (size - 1) if size > 1 else np.ones(1)
    novelty = _min_max(-np.log2([max(int(rating_counts.get(movie_id, 1)), 1) for movie_id in movie_ids]))
    similarity = _genre_jaccard(movie_ids, genres)

    base = (1.0 - weight) * relevance + weight * NOVELTY_SHARE * novelty
    diversity_weight = weight * (1.0 - NOVELTY_SHARE)
    closest = np.zeros(size)  # max similarity of each candidate to the chosen movies
    available = np.ones(size, dtype=bool)
    order: list[int] = []
    for _ in range(min(n, size)):
        value = np.where(available, base + diversity_weight * (1.0 - closest), -np.inf)
        chosen = int(np.argmax(value))  # argmax returns the first maximum: ties keep CF order
        order.append(chosen)
        available[chosen] = False
        closest = np.maximum(closest, similarity[:, chosen])
    return [unique[index] for index in order]


def _min_max(values: Sequence[float]) -> np.ndarray:
    """Rescale to [0, 1]; a constant vector becomes all zeros (no candidate is more novel)."""
    values = np.asarray(values, dtype=float)
    spread = values.max() - values.min()
    return (values - values.min()) / spread if spread > 0 else np.zeros_like(values)


def _genre_jaccard(movie_ids: Sequence[int], genres: Mapping[int, Iterable[str]]) -> np.ndarray:
    """Pairwise Jaccard similarity of the movies' genre sets (0 when either set is empty)."""
    sets = [set(genres.get(movie_id, ())) for movie_id in movie_ids]
    vocabulary = sorted(set().union(*sets))
    if not vocabulary:
        return np.zeros((len(movie_ids), len(movie_ids)))
    matrix = np.array([[genre in movie_genres for genre in vocabulary] for movie_genres in sets], dtype=float)
    intersection = matrix @ matrix.T
    sizes = matrix.sum(axis=1)
    union = sizes[:, None] + sizes[None, :] - intersection
    return np.divide(intersection, union, out=np.zeros_like(intersection), where=union > 0)
