from tools.mutation_summary import (
    MAX_INLINE_VALUE_CHARS,
    MAX_PREVIEW_CHARS,
    MISSING_VALUE,
    build_mutation_summary,
)


def test_mutation_summary_keeps_small_values_exact_and_marks_missing() -> None:
    summary = build_mutation_summary(
        operation="asset.create",
        entity_kind="character",
        entity_id="lin_cen",
        path="src/characters/lin_cen.md",
        before=MISSING_VALUE,
        after={"name": "林岑", "goal": "守住旧城"},
        result_revision="sha256:after",
        field_prefix="entity",
        flatten=False,
    )

    item = summary["items"][0]
    assert item["before"]["kind"] == "missing"
    assert item["after"]["value"] == {"name": "林岑", "goal": "守住旧城"}
    assert item["execution_status"] == "committed"


def test_mutation_summary_never_presents_a_long_excerpt_as_the_exact_value() -> None:
    long_text = "雨夜钟声" * (MAX_INLINE_VALUE_CHARS + 1)
    summary = build_mutation_summary(
        operation="document.update",
        entity_kind="manuscript",
        entity_id="ch_001",
        path="data/manuscript/arc_001/ch_001.md",
        before="旧稿",
        after=long_text,
        source_revision="sha256:before",
        result_revision="sha256:after",
        field_prefix="content",
        flatten=False,
    )

    after = summary["items"][0]["after"]
    assert after["value"] is None
    assert after["truncated"] is True
    assert after["units"] == len(long_text)
    assert len(after["preview"]) == MAX_PREVIEW_CHARS
    assert after["sha256"].startswith("sha256:")
