"""Unit tests for normalize_bible() — bible roles/relationships soft validation."""
import pytest

from app.models import Bible, StoryInput
from app.pipeline.story_engine import (apply_user_hints, normalize_bible,
                                       _scene_pass_max_tokens,
                                       _user_hint_block)


def make_bible(characters=None, objects=None, locations=None, relationships=None) -> Bible:
    return Bible.model_validate({
        "style": "s",
        "world": "w",
        "characters": characters or [],
        "locations": locations or [],
        "objects": objects or [],
        "relationships": relationships or [],
    })


def char(id_, role="supporting"):
    return {"id": id_, "name": id_, "visual_dna": "x", "role": role}


def obj(id_):
    return {"id": id_, "name": id_, "visual_dna": "x"}


def loc(id_):
    return {"id": id_, "name": id_, "visual_dna": "x"}


def rel(source, target, type_):
    return {"source": source, "target": target, "type": type_}


def test_old_bible_without_new_fields_gains_defaults():
    b = Bible.model_validate({
        "style": "s",
        "characters": [{"id": "char_a", "name": "A", "visual_dna": "x"}],
        "locations": [], "objects": [],
    })
    assert b.characters[0].role == "supporting"
    assert b.relationships == []


def test_scene_pass_max_tokens_scales_for_large_scripts():
    assert _scene_pass_max_tokens(10) == 8192
    assert _scene_pass_max_tokens(70) == 12200
    assert _scene_pass_max_tokens(150) == 25000


def test_unknown_role_falls_back_to_supporting_with_warning():
    b = make_bible(characters=[char("char_a", "wizard")])
    warnings = normalize_bible(b)
    assert b.characters[0].role == "supporting"
    assert any("unknown role" in w for w in warnings)


def test_role_aliases_and_case_normalized():
    b = make_bible(characters=[
        char("char_a", "Hero"), char("char_b", "Child Villain"), char("char_c", "henchman"),
    ])
    normalize_bible(b)
    assert [c.role for c in b.characters] == ["protagonist", "villain_lieutenant", "minion"]


def test_child_of_and_serves_flip_direction():
    b = make_bible(
        characters=[char("char_a"), char("char_b")],
        relationships=[rel("char_a", "char_b", "child_of"),
                       rel("char_a", "char_b", "serves")],
    )
    normalize_bible(b)
    kept = {(r.source, r.type, r.target) for r in b.relationships}
    assert kept == {("char_b", "parent_of", "char_a"), ("char_b", "commands", "char_a")}


def test_invalid_edges_dropped_with_warnings():
    b = make_bible(
        characters=[char("char_a"), char("char_b")],
        objects=[obj("obj_s")],
        locations=[loc("loc_x")],
        relationships=[
            rel("char_a", "char_ghost", "ally_of"),   # unknown id
            rel("char_a", "loc_x", "ally_of"),        # location endpoint
            rel("char_a", "char_a", "ally_of"),       # self-edge
            rel("char_a", "char_b", "besties"),       # unknown type
            rel("char_a", "obj_s", "enemy_of"),       # non-owns/uses on object
            rel("obj_s", "char_a", "uses"),           # owns/uses must be char->object
        ],
    )
    warnings = normalize_bible(b)
    assert b.relationships == []
    assert len(warnings) >= 6  # 6 drops (+ zero-relationship notices)


def test_symmetric_duplicates_deduped():
    b = make_bible(
        characters=[char("char_a"), char("char_b")],
        relationships=[rel("char_a", "char_b", "enemy_of"),
                       rel("char_b", "char_a", "enemy_of")],
    )
    warnings = normalize_bible(b)
    assert len(b.relationships) == 1
    assert any("duplicate" in w for w in warnings)


def test_directed_reverse_edges_are_not_deduped():
    # a mentors b and b mentors a is contradictory but directional — both kept
    b = make_bible(
        characters=[char("char_a"), char("char_b")],
        relationships=[rel("char_a", "char_b", "mentors"),
                       rel("char_b", "char_a", "mentors")],
    )
    normalize_bible(b)
    assert len(b.relationships) == 2


def test_character_without_relationships_warns_but_keeps():
    b = make_bible(characters=[char("char_lonely", "protagonist")])
    warnings = normalize_bible(b)
    assert any("no relationships" in w for w in warnings)
    assert b.characters[0].role == "protagonist"


def test_clean_bible_passes_untouched():
    b = make_bible(
        characters=[char("char_v", "villain"), char("char_m", "minion")],
        objects=[obj("obj_s")],
        relationships=[rel("char_v", "char_m", "commands"),
                       rel("char_m", "obj_s", "uses")],
    )
    warnings = normalize_bible(b)
    assert warnings == []
    assert len(b.relationships) == 2


# ------------------------------------------------ apply_user_hints (input-time)
def story_input(reference_images=None, relationship_hints=None) -> StoryInput:
    return StoryInput.model_validate({
        "topic": "a lone hunter fights a warlord who rules a dead city ruled by cold fear",
        "genre": "sci-fi", "ending": "bittersweet", "image_style": "cinematic_realistic",
        "reference_images": reference_images or [],
        "relationship_hints": relationship_hints or [],
    })


def test_user_role_hint_overrides_generated_role_by_name():
    b = make_bible(characters=[char("char_vex", "supporting")])
    b.characters[0].name = "Warlord Vex"
    inp = story_input(reference_images=[
        {"kind": "character", "name": "Vex", "role": "villain", "url": "http://x"}])
    apply_user_hints(b, inp)
    normalize_bible(b)
    assert b.characters[0].role == "villain"   # "Vex" fuzzy-matched "Warlord Vex"


def test_user_relationship_hint_wired_to_ids():
    b = make_bible(
        characters=[char("char_v"), char("char_m")],
        objects=[obj("obj_s")],
    )
    b.characters[0].name = "Vex"
    b.characters[1].name = "Grub"
    b.objects[0].name = "Plasma Blade"
    inp = story_input(relationship_hints=[
        {"source": "Vex", "target": "Grub", "type": "commands", "label": "loyal"},
        {"source": "Vex", "target": "Plasma Blade", "type": "uses"},
    ])
    apply_user_hints(b, inp)
    normalize_bible(b)
    edges = {(r.source, r.type, r.target) for r in b.relationships}
    assert ("char_v", "commands", "char_m") in edges
    assert ("char_v", "uses", "obj_s") in edges


def test_unresolvable_hint_is_skipped_with_warning():
    b = make_bible(characters=[char("char_a")])
    b.characters[0].name = "Ana"
    inp = story_input(relationship_hints=[
        {"source": "Ana", "target": "Nobody", "type": "loves"}])
    warnings = apply_user_hints(b, inp)
    assert b.relationships == []
    assert any("Nobody" in w for w in warnings)


def test_hint_block_empty_when_nothing_drawn():
    assert _user_hint_block(story_input()) == ""


def test_hint_block_renders_roles_and_edges():
    inp = story_input(
        reference_images=[{"kind": "character", "name": "Vex", "role": "villain", "url": "http://x"}],
        relationship_hints=[{"source": "Vex", "target": "Grub", "type": "commands"}],
    )
    block = _user_hint_block(inp)
    assert 'character "Vex" MUST have role: villain' in block
    assert '"Vex" commands "Grub"' in block
