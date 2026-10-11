import gzip
import os
import time
from datetime import datetime, timezone

from app.log_archive import MB, LogArchive


def names(directory):
    return sorted(p.name for p in directory.iterdir() if p.is_file())


def test_parts_are_named_by_run_and_part(tmp_path):
    archive = LogArchive(tmp_path)
    log = archive.open("run", "r1")
    log.write('{"event": "a"}')
    assert names(tmp_path) == ["run-r1.001.jsonl"]


def test_archive_rolls_compresses_and_keeps_writing(tmp_path):
    archive = LogArchive(tmp_path)
    log = archive.open("run", "r1")
    log.write('{"event": "a"}')
    result = archive.archive("nightly")
    log.write('{"event": "b"}')

    assert result["archived"] == ["run-r1.001.jsonl.gz"]
    assert names(tmp_path) == ["run-r1.002.jsonl"]
    assert gzip.decompress((tmp_path / "history" / "run-r1.001.jsonl.gz").read_bytes()) == b'{"event": "a"}\n'


def test_archive_skips_an_empty_current_part(tmp_path):
    archive = LogArchive(tmp_path)
    log = archive.open("run", "r1")
    assert archive.archive("nightly")["archived"] == []
    assert log.part == 1


def test_startup_archives_every_log_family_left_behind(tmp_path):
    (tmp_path / "run-old.001.jsonl").write_text("{}\n")
    (tmp_path / "events-old.004.jsonl").write_text("{}\n")
    (tmp_path / "run-legacy.jsonl").write_text("{}\n")  # before parts existed
    archive = LogArchive(tmp_path)
    archive.open("run", "new")

    result = archive.archive("startup")
    assert sorted(result["archived"]) == ["events-old.004.jsonl.gz", "run-legacy.jsonl.gz", "run-old.001.jsonl.gz"]
    assert names(tmp_path) == []


def test_a_reopened_run_continues_at_its_next_part(tmp_path):
    archive = LogArchive(tmp_path)
    archive.open("run", "r1").write("{}")
    archive.archive("startup")

    reloaded = LogArchive(tmp_path).open("run", "r1")  # e.g. a code reload with the same run id
    assert reloaded.part == 2


def test_history_cap_deletes_oldest_first_but_never_the_new_parts(tmp_path):
    archive = LogArchive(tmp_path, history_max_mb=0.001)  # ~1 KB
    history = tmp_path / "history"
    for i, name in enumerate(["run-a.001.jsonl.gz", "run-b.001.jsonl.gz"]):
        (history / name).write_bytes(os.urandom(600))
        os.utime(history / name, (1000 + i, 1000 + i))
    log = archive.open("run", "c")
    log.write(os.urandom(1500).hex())  # incompressible: ~1.6 KB gzipped, over the cap alone

    result = archive.archive("nightly")
    assert result["deleted"] == ["run-a.001.jsonl.gz", "run-b.001.jsonl.gz"]
    assert names(history) == ["run-c.001.jsonl.gz"]  # over the cap on its own, but just archived


def test_size_trigger_archives_in_the_background(tmp_path):
    archive = LogArchive(tmp_path, max_file_mb=100 / MB)  # 100 bytes
    done = []
    archive.on_archived = done.append
    log = archive.open("run", "r1")
    for _ in range(5):
        log.write("x" * 30)

    deadline = time.time() + 5
    while not done and time.time() < deadline:
        time.sleep(0.01)
    assert done and done[0]["reason"] == "size"
    assert done[0]["archived"] == ["run-r1.001.jsonl.gz"]
    assert log.part == 2


def test_seconds_until_nightly(tmp_path):
    archive = LogArchive(tmp_path, nightly_utc="10:00")
    assert archive.seconds_until_nightly(datetime(2026, 10, 11, 9, 0, tzinfo=timezone.utc)) == 3600
    assert archive.seconds_until_nightly(datetime(2026, 10, 11, 10, 0, tzinfo=timezone.utc)) == 24 * 3600
    assert LogArchive(tmp_path).seconds_until_nightly() is None


def test_from_config_honors_the_dir_override(tmp_path, monkeypatch):
    monkeypatch.setenv("SCHEMATICS_LOGS_DIR", str(tmp_path / "volume" / "logs"))
    archive = LogArchive.from_config({"logs": {"enabled": True, "dir": "logs", "history_max_mb": 5}}, tmp_path)
    assert archive.directory == tmp_path / "volume" / "logs"
    assert archive.history.is_dir()
    assert archive.history_max_bytes == 5 * MB
    assert LogArchive.from_config({"logs": {"enabled": False}}, tmp_path) is None
