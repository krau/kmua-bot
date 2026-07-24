from kmua.plugins.slash import _strip_trigger_prefix


def test_strip_trigger_prefix_only_removes_leading_escape_characters():
    assert _strip_trigger_prefix("/test") == "test"
    assert _strip_trigger_prefix("test/data/path") == "test/data/path"
