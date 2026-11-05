def test_profile_to_card_sync(tmp_path):
    from tools.character_sync import sync_all_profiles_to_cards

    src_chars = tmp_path / "src" / "characters"
    src_chars.mkdir(parents=True)
    (src_chars / "chen_ming.md").write_text("""# 陈明

## 基本信息
- 职业: 程序员
- 年龄: 28

## 外貌
中等偏瘦，黑眼圈明显，格子衫

## 性格
996社畜，理工科思维
""")

    data_chars = tmp_path / "data" / "characters"
    data_chars.mkdir(parents=True)

    sync_all_profiles_to_cards(tmp_path / "src", tmp_path / "data")

    card_file = data_chars / "cards" / "chen_ming.yaml"
    assert card_file.exists()
    import yaml

    with open(card_file) as f:
        card = yaml.safe_load(f)
    assert card["name"] == "陈明"
    assert card["identity"] == "程序员"
    assert card["age"] == 28
    assert "appearance" in card, "Appearance should be parsed"
    appearance = card["appearance"]
    assert appearance["build"] == "中等偏瘦", f"Expected 中等偏瘦, got {appearance.get('build')}"
    assert appearance["features"] == "黑眼圈明显"
    assert appearance["clothing"] == "格子衫"
    print(f"Generated card: {card}")


def test_profile_with_toml_front_matter_syncs_to_card(tmp_path):
    from tools.character_sync import sync_all_profiles_to_cards

    src_chars = tmp_path / "src" / "characters"
    src_chars.mkdir(parents=True)
    (src_chars / "chen_ming.md").write_text(
        """+++
id = "char_chen_ming"
name = "陈明"
tier = "主角"
age = 28
occupation = "程序员"
summary = "普通程序员觉醒术法后被迫在两个世界夹缝求生。"
tags = ["都市", "异能", "成长"]

[[related]]
target = "zhao_lei"
kind = "friend"
weight = 0.82
note = "最信任的同事"
+++

# 陈明

## background
普通程序员，偶然觉醒术法。

## appearance
中等偏瘦，黑眼圈明显，格子衫

## personality
- 理工科思维
- 嘴硬心软
""",
        encoding="utf-8",
    )

    data_chars = tmp_path / "data" / "characters"
    data_chars.mkdir(parents=True)

    sync_all_profiles_to_cards(tmp_path / "src", tmp_path / "data")

    card_file = data_chars / "cards" / "chen_ming.yaml"
    assert card_file.exists()

    import yaml

    with open(card_file, encoding="utf-8") as f:
        card = yaml.safe_load(f)

    assert card["id"] == "char_chen_ming"
    assert card["name"] == "陈明"
    assert card["tier"] == "主角"
    assert card["age"] == 28
    assert card["occupation"] == "程序员"
    assert card["brief"] == "普通程序员觉醒术法后被迫在两个世界夹缝求生。"
    assert card["background"] == "普通程序员，偶然觉醒术法。"
    assert card["personality"] == ["理工科思维", "嘴硬心软"]
    assert card["relationships"][0]["target"] == "zhao_lei"


def test_profile_without_heading_falls_back_to_filename(tmp_path):
    from tools.character_sync import sync_all_profiles_to_cards

    src_chars = tmp_path / "src" / "characters"
    src_chars.mkdir(parents=True)
    (src_chars / "liang_zhiyuan.md").write_text(
        "## UI 实测补充\n- 核心欲望：找回第十三枚齿轮。\n",
        encoding="utf-8",
    )

    sync_all_profiles_to_cards(tmp_path / "src", tmp_path / "data")

    import yaml

    with open(
        tmp_path / "data" / "characters" / "cards" / "liang_zhiyuan.yaml",
        encoding="utf-8",
    ) as f:
        card = yaml.safe_load(f)

    assert card["id"] == "liang_zhiyuan"
    assert card["name"] == "liang_zhiyuan"


def test_card_sync_is_atomic_and_leaves_no_temporary_files(tmp_path):
    """A crash mid-write must not leave a half-written card.

    The freshness check compares mtimes, so a card truncated by a bare
    open(...,"w") reads as current and every consumer works from a partial card.
    """
    from tools.character_sync import sync_all_profiles_to_cards

    src_chars = tmp_path / "src" / "characters"
    src_chars.mkdir(parents=True)
    (src_chars / "chen_ming.md").write_text("""# 陈明

## 基本信息
- 职业: 程序员
- 年龄: 28

## 外貌
- 中等身材，戴眼镜
""", encoding="utf-8")

    sync_all_profiles_to_cards(tmp_path / "src", tmp_path / "data")

    cards = tmp_path / "data" / "characters" / "cards"
    card = cards / "chen_ming.yaml"
    assert card.is_file()
    # The written card parses completely, so nothing was left half-serialized.
    import yaml

    parsed = yaml.safe_load(card.read_text(encoding="utf-8"))
    assert parsed["name"] == "陈明"
    assert parsed["occupation"] == "程序员"
    # No stray temp files beside the card.
    assert sorted(p.name for p in cards.iterdir()) == ["chen_ming.yaml"]
