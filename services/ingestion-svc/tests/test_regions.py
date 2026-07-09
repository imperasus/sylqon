"""Region model: platform → cluster mapping + normalization."""
from app import regions


def test_cluster_mapping_covers_all_clusters():
    assert regions.cluster_for("euw1") == "europe"
    assert regions.cluster_for("na1") == "americas"
    assert regions.cluster_for("kr") == "asia"
    assert regions.cluster_for("oc1") == "sea"


def test_cluster_for_unknown_defaults_to_europe():
    assert regions.cluster_for("bogus") == "europe"
    assert regions.cluster_for(None) == "europe"


def test_normalize_lowercases_known_and_defaults_unknown():
    assert regions.normalize("NA1") == "na1"
    assert regions.normalize("bogus") == "euw1"
    assert regions.normalize(None) == "euw1"


def test_is_valid():
    assert regions.is_valid("kr")
    assert not regions.is_valid("nope")
    assert not regions.is_valid(None)


def test_every_choice_has_a_cluster():
    for code, _label in regions.PLATFORM_CHOICES:
        assert code in regions.PLATFORM_TO_CLUSTER
