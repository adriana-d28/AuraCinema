"""Tests for the Discovery Mode re-ranking (ml/src/discovery_mode.py).

Kept to the two properties the API relies on: the output is always a valid subset of
the candidates, and the three modes move from the CF order towards exploration.
"""

import pytest
from src.discovery_mode import DISCOVERY_WEIGHTS, rerank

# CF candidates, best first. The top four are popular dramas; the rest are rarely rated
# movies of other genres, i.e. more novel and more diverse but less relevant.
CANDIDATES = [(1, 3.0), (2, 2.8), (3, 2.6), (4, 2.4), (5, 1.0), (6, 0.8), (7, 0.6), (8, 0.4)]
GENRES = {1: ["Drama"], 2: ["Drama"], 3: ["Drama"], 4: ["Drama"],
          5: ["Comedy"], 6: ["Horror"], 7: ["Western"], 8: []}
COUNTS = {1: 90000, 2: 80000, 3: 70000, 4: 60000, 5: 500, 6: 400, 7: 300, 8: 200}


@pytest.mark.parametrize("mode", sorted(DISCOVERY_WEIGHTS))
def test_result_is_a_valid_subset_of_the_candidates(mode):
    candidates = [*CANDIDATES, (1, 9.9)]  # a repeated movie keeps its first position only
    result = rerank(candidates, 5, mode, GENRES, COUNTS)

    ids = [movie_id for movie_id, _ in result]
    assert len(ids) == len(set(ids)) == 5
    assert set(result) <= set(CANDIDATES)  # original scores kept, nothing invented
    assert len(rerank(CANDIDATES[:2], 5, mode, GENRES, COUNTS)) == 2  # short pool -> short list
    with pytest.raises(ValueError):
        rerank(CANDIDATES, 5, "random", GENRES, COUNTS)


def test_modes_trade_relevance_for_exploration_in_order():
    def top4(mode):
        return [movie_id for movie_id, _ in rerank(CANDIDATES, 4, mode, GENRES, COUNTS)]

    safe, balanced, adventurous = top4("safe"), top4("balanced"), top4("adventurous")
    assert safe[0] == 1 and balanced[0] == 1  # the best CF candidate still leads

    def explored(ids):  # movies taken from outside the original CF top 4
        return len(set(ids) - {1, 2, 3, 4})

    assert explored(safe) <= explored(balanced) <= explored(adventurous)
    assert explored(safe) < explored(adventurous)
