from __future__ import annotations

import unittest

import nltk

from orchestrator.lexicon import (
    DEFAULT_NLTK_DATA_DIR,
    configure_nltk_data_dir,
    frequency,
    rank_synonyms_by_frequency,
    synonyms,
)


def _wordnet_available() -> bool:
    configure_nltk_data_dir()
    try:
        try:
            nltk.data.find("corpora/wordnet")
        except LookupError:
            nltk.data.find("corpora/wordnet.zip")
        try:
            nltk.data.find("corpora/omw-1.4")
        except LookupError:
            nltk.data.find("corpora/omw-1.4.zip")
        return True
    except LookupError:
        return False


@unittest.skipUnless(
    _wordnet_available(),
    f"WordNet not found in {DEFAULT_NLTK_DATA_DIR}. Run: python scripts/setup_wordnet.py",
)
class LexiconTests(unittest.TestCase):
    def test_synonyms_car_not_empty(self) -> None:
        values = synonyms("car", max_results=30)
        self.assertTrue(values)
        plausible = {"auto", "automobile", "machine", "motorcar"}
        self.assertTrue(any(item in plausible for item in values))

    def test_ranked_synonyms_sorted_desc(self) -> None:
        ranked = rank_synonyms_by_frequency("car", max_results=20)
        self.assertTrue(ranked)
        scores = [score for _, score in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_frequency_common_vs_uncommon(self) -> None:
        self.assertGreater(frequency("the"), frequency("xylophone"))


if __name__ == "__main__":
    unittest.main()
