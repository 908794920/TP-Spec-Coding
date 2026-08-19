from cli.review_locator import locate_existing_code


def test_locates_code_in_diff_hunk_new_side():
    diffs = [{"new_path": "a.py", "old_path": "a.py", "diff": "@@ -1,2 +1,3 @@\n a = 1\n+b = 2\n c = 3\n", "new_file_content": "a = 1\nb = 2\nc = 3\n"}]
    loc = locate_existing_code("b = 2", diffs, preferred_path="a.py")
    assert (loc.path, loc.start_line, loc.end_line, loc.source) == ("a.py", 2, 2, "hunk")


def test_falls_back_to_full_file_when_hunk_has_no_match():
    diffs = [{"new_path": "a.py", "old_path": "a.py", "diff": "@@ -1 +1 @@\n-old\n+new\n", "new_file_content": "first\ntarget()\nlast\n"}]
    loc = locate_existing_code("target()", diffs, preferred_path="a.py")
    assert (loc.path, loc.start_line, loc.source) == ("a.py", 2, "file")


def test_unique_cross_file_match_relocates_path():
    diffs = [
        {"new_path": "wrong.py", "old_path": "wrong.py", "diff": "", "new_file_content": "nothing\n"},
        {"new_path": "right.py", "old_path": "right.py", "diff": "", "new_file_content": "x\nneedle()\ny\n"},
    ]
    loc = locate_existing_code("needle()", diffs, preferred_path="wrong.py")
    assert (loc.path, loc.start_line, loc.source) == ("right.py", 2, "cross-file")


def test_ambiguous_cross_file_match_refuses_to_guess():
    diffs = [
        {"new_path": "wrong.py", "old_path": "wrong.py", "diff": "", "new_file_content": "nothing\n"},
        {"new_path": "one.py", "old_path": "one.py", "diff": "", "new_file_content": "needle()\n"},
        {"new_path": "two.py", "old_path": "two.py", "diff": "", "new_file_content": "needle()\n"},
    ]
    assert locate_existing_code("needle()", diffs, preferred_path="wrong.py") is None
