from pathlib import Path

from agent_redteam import secret_scan
from agent_redteam.secret_scan import find_secret_files

KEY = "sk-test-0123456789abcdef"


def test_files_holding_the_value_are_listed_and_others_are_not(tmp_path):
    (tmp_path / "a.json").write_text('{"out": "OPENAI_API_KEY=%s"}' % KEY)
    (tmp_path / "b.json").write_text("nothing here")
    got = find_secret_files([tmp_path], ["K"], env={"K": KEY})
    assert got == {"K": [str(tmp_path / "a.json")]}


def test_directories_are_searched_recursively_and_single_files_are_accepted(tmp_path):
    (tmp_path / "d" / "e").mkdir(parents=True)
    (tmp_path / "d" / "e" / "x.db").write_bytes(b"\x00\x01" + KEY.encode() + b"\x02")
    one = tmp_path / "one.txt"
    one.write_text(KEY)
    got = find_secret_files([tmp_path / "d", one], ["K"], env={"K": KEY})
    assert sorted(got["K"]) == sorted([str(tmp_path / "d" / "e" / "x.db"), str(one)])


def test_unset_and_too_short_values_are_skipped_not_searched(tmp_path):
    (tmp_path / "a.txt").write_text("true 1 true 1")
    assert find_secret_files([tmp_path], ["SHORT", "MISSING"], env={"SHORT": "true"}) == {}


def test_a_missing_path_is_ignored(tmp_path):
    assert find_secret_files([tmp_path / "nope"], ["K"], env={"K": KEY}) == {"K": []}


def test_main_exits_1_and_never_prints_the_value(tmp_path, monkeypatch, capsys):
    f = tmp_path / "r.json"
    f.write_text(KEY)
    monkeypatch.setenv("RT_K", KEY)
    monkeypatch.setattr("sys.argv", ["x", "--env", "RT_K", str(f)])
    assert secret_scan.main() == 1
    out = capsys.readouterr().out
    assert str(f) in out and KEY not in out


def test_main_exits_0_when_clean_and_says_when_a_variable_was_not_checked(tmp_path, monkeypatch, capsys):
    (tmp_path / "r.json").write_text("clean")
    monkeypatch.setenv("RT_K", KEY)
    monkeypatch.delenv("RT_UNSET", raising=False)
    monkeypatch.setattr("sys.argv", ["x", "--env", "RT_K", "--env", "RT_UNSET", str(tmp_path)])
    assert secret_scan.main() == 0
    out = capsys.readouterr().out
    assert "RT_K: not found" in out and "RT_UNSET: not set" in out and "NOT checked" in out


def test_an_unreadable_file_does_not_abort_the_scan(tmp_path, monkeypatch):
    bad, good = tmp_path / "a-bad.txt", tmp_path / "b-good.txt"
    bad.write_text("x")
    good.write_text(KEY)
    real = Path.read_bytes

    def read_bytes(self):
        if self.name == "a-bad.txt":
            raise PermissionError("denied")
        return real(self)
    monkeypatch.setattr(Path, "read_bytes", read_bytes)
    assert find_secret_files([tmp_path], ["K"], env={"K": KEY}) == {"K": [str(good)]}
