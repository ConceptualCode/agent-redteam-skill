from agent_redteam.llm_rubric import build_assertions, rubric_for


def test_rubric_for_covers_secrets_then_markers_and_names_the_bypass_forms():
    rubrics = rubric_for(["S3CRET"], ["MARK-9"])
    assert len(rubrics) == 2
    assert '"S3CRET"' in rubrics[0] and "spelled out" in rubrics[0] and "encoded" in rubrics[0] and "paraphrased" in rubrics[0]
    assert 'associated with "MARK-9"' in rubrics[1] and "restating it in different words" in rubrics[1]


def test_rubric_for_is_empty_with_nothing_to_rubric():
    assert rubric_for([], []) == []


def test_rubric_for_handles_several_of_each():
    rubrics = rubric_for(["A", "B"], ["M1"])
    assert len(rubrics) == 3
    assert '"A"' in rubrics[0] and '"B"' in rubrics[1] and '"M1"' in rubrics[2]


def test_build_assertions_wraps_each_rubric_as_an_llm_rubric_assertion():
    out = build_assertions(["S3CRET"], ["MARK-9"])
    assert out == [{"type": "llm-rubric", "value": rubric_for(["S3CRET"], [])[0]},
                   {"type": "llm-rubric", "value": rubric_for([], ["MARK-9"])[0]}]


def test_build_assertions_is_empty_with_no_secrets_or_markers():
    assert build_assertions([], []) == []
