"""The grader and the catalogue views - no model, no network."""
import json

import pytest

from hittbar import catalog
from hittbar.evaluate import correct, load_tasks, page_correct
from hittbar.scrape import own_text, parse_page


def test_every_gold_id_exists():
    ids = set(catalog.product_ids())
    for t in load_tasks():
        assert set(t["accept"]) <= ids, t["id"]


def test_product_ids_are_unique():
    ids = catalog.product_ids()
    assert len(ids) == len(set(ids))


def test_none_task_only_accepts_none():
    t = {"accept": []}
    assert correct(t, "none")
    assert not correct(t, "buy-car-insurance-dk")


def test_answerable_task_rejects_none():
    t = {"accept": ["buy-car-insurance-dk"]}
    assert not correct(t, "none")
    assert not page_correct(t, "none")


def test_sibling_on_same_page_is_page_correct_but_not_correct():
    t = {"accept": ["request-quote-branded-car-insurance-se"]}
    assert not correct(t, "buy-branded-car-insurance-se")
    assert page_correct(t, "buy-branded-car-insurance-se")


def test_wrong_country_is_wrong_at_both_levels():
    t = {"accept": ["buy-car-insurance-dk"]}
    assert not correct(t, "buy-car-insurance-no")
    assert not page_correct(t, "buy-car-insurance-no")


def test_render_is_byte_stable_so_it_caches():
    assert catalog.render("published") == catalog.render("published")


def test_published_view_carries_no_generated_text():
    assert "Agent guide:" not in catalog.render("published")
    assert "Page text:" not in catalog.render("published")


def test_duplicate_api_listings_are_collapsed():
    view = catalog.render("published")
    block = view.split("[page: communication/event-subscription]")[1].split("## ")[0]
    assert block.count("API Event Subscription Management:") == 1


def test_unknown_condition_raises():
    with pytest.raises(ValueError):
        catalog.render("everything")


def test_related_pages_do_not_leak_into_page_text():
    sd = {"mainContentBody": {"propertyDataType": "PropertyXhtmlString",
                              "value": "<p>Swedish car insurance for passenger cars and vans.</p>"},
          "relatedPagesContentArea": {"expandedValue": [{"mainContentPreamble": {
              "propertyDataType": "PropertyLongString",
              "value": "Enhance your Norwegian customers mobility experience with our APIs."}}]}}
    text = own_text(sd)
    assert "Swedish" in text and "Norwegian" not in text


def test_parse_page_skips_category_pages():
    html = ('<script id="__NEXT_DATA__" type="application/json">'
            + json.dumps({"props": {"pageProps": {"page": {"_typeName": "ProductCategoryPage"}}}})
            + "</script>")
    assert parse_page("https://developer.if-insurance.com/apis/mobility/", html) is None


def test_bm25_ranks_the_matching_document_first():
    from hittbar.search import BM25
    index = BM25({"a": "travel insurance quote Finland", "b": "car insurance Denmark buy",
                  "c": "home contents insurance Norway"})
    assert index.rank("buy car insurance in Denmark")[0] == "b"


def test_bm25_ranking_is_deterministic_on_ties():
    from hittbar.search import BM25
    index = BM25({"b": "same words", "a": "same words"})
    assert index.rank("same") == ["a", "b"]


def test_every_answerable_task_has_a_searchable_document():
    from hittbar.search import documents
    for cond in catalog.CONDITIONS:
        docs = documents(cond)
        for t in load_tasks():
            assert all(a in docs for a in t["accept"]), (cond, t["id"])
