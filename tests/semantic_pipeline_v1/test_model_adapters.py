import math

from guardian_truth.semantic_pipeline_v1.models.nli import NLIFirewall


class _Config:
    id2label = {0: "contradiction", 1: "entailment", 2: "neutral"}


class _Inner:
    config = _Config()


class FakeCrossEncoder:
    model = _Inner()

    def predict(self, pairs, *, apply_softmax):
        assert pairs == [("source", "rendering")]
        assert apply_softmax is False
        return [[2.0, 1.0, 0.0]]


def test_nli_preserves_raw_logits_and_normalizes_scores():
    evidence = NLIFirewall("fake-nli", FakeCrossEncoder()).check("source", "rendering")
    assert evidence.logits == (2.0, 1.0, 0.0)
    assert evidence.label == "CONTRADICTION"
    assert math.isclose(sum(evidence.scores.values()), 1.0)
    assert evidence.scores["CONTRADICTION"] > evidence.scores["ENTAILMENT"]
