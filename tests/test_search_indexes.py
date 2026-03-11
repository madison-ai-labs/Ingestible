from ingestible.search.bm25_store import BM25Store
from ingestible.search.concept_index import ConceptIndex


def test_bm25_roundtrip(tmp_path):
    store = BM25Store()
    store.add_documents(
        ["c1", "c2", "c3"],
        [
            "machine learning algorithms for classification",
            "deep learning neural networks",
            "cooking recipes for pasta dishes",
        ],
    )
    store.build()

    results = store.query("machine learning", n_results=2)
    assert len(results) > 0
    assert results[0][0] == "c1"  # best match

    # Persistence
    path = tmp_path / "bm25.pkl"
    store.save(path)
    loaded = BM25Store.load(path)
    results2 = loaded.query("machine learning", n_results=2)
    assert results2[0][0] == "c1"


def test_concept_index_roundtrip(tmp_path):
    idx = ConceptIndex()
    idx.add_many(["machine learning", "neural networks", "deep learning"], "c1")
    idx.add_many(["neural networks", "backpropagation"], "c2")
    idx.add("cooking", "c3")

    results = idx.lookup("neural networks")
    assert "c1" in results
    assert "c2" in results
    assert "c3" not in results

    # Partial match
    partial_results = idx.lookup("learning")
    assert "c1" in partial_results  # matches "machine learning" and "deep learning"

    # Persistence
    path = tmp_path / "concepts.json"
    idx.save(path)
    loaded = ConceptIndex.load(path)
    assert loaded.lookup("neural networks") == results
