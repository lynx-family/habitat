import os
import shutil
from pathlib import Path

from core.utils import extract_archive


def test_extract_archive(tmp_path):
    artifact_path = os.path.join(tmp_path, "test_extract_archive_artifact")

    # prepare a file with mode 777 and a dir with mode 711
    with open(test_file := f"{tmp_path}/test-file", "w") as f:
        f.write("test")
    os.chmod(test_file, mode=0o777)
    os.makedirs(test_dir := f"{tmp_path}/test-dir", mode=0o711)

    origin_file_stat = os.stat(test_file).st_mode
    origin_dir_stat = os.stat(test_dir).st_mode

    # make archive
    os.chdir(tmp_path)
    shutil.make_archive(f"{artifact_path}/archive", "gztar")
    shutil.make_archive(f"{artifact_path}/archive", "zip")
    shutil.make_archive(f"{artifact_path}/archive", "xztar")
    shutil.make_archive(f"{artifact_path}/archive", "bztar")
    shutil.make_archive(f"{artifact_path}/archive", "tar")

    # extract archive
    extract_archive(f"{artifact_path}/archive.tar.gz", f"{artifact_path}/gz", [])
    extract_archive(f"{artifact_path}/archive.zip", f"{artifact_path}/zip", [])
    extract_archive(f"{artifact_path}/archive.tar.xz", f"{artifact_path}/xz", [])
    extract_archive(f"{artifact_path}/archive.tar.bz2", f"{artifact_path}/bz", [])
    extract_archive(f"{artifact_path}/archive.tar", f"{artifact_path}/tar", [])

    # assert mode equals with the original mode
    assert os.stat(f"{artifact_path}/gz/test-dir").st_mode == origin_dir_stat
    assert os.stat(f"{artifact_path}/gz/test-file").st_mode == origin_file_stat
    assert os.stat(f"{artifact_path}/zip/test-dir").st_mode == origin_dir_stat
    assert os.stat(f"{artifact_path}/zip/test-file").st_mode == origin_file_stat
    assert os.stat(f"{artifact_path}/xz/test-dir").st_mode == origin_dir_stat
    assert os.stat(f"{artifact_path}/xz/test-file").st_mode == origin_file_stat
    assert os.stat(f"{artifact_path}/bz/test-dir").st_mode == origin_dir_stat
    assert os.stat(f"{artifact_path}/bz/test-file").st_mode == origin_file_stat
    assert os.stat(f"{artifact_path}/tar/test-dir").st_mode == origin_dir_stat
    assert os.stat(f"{artifact_path}/tar/test-file").st_mode == origin_file_stat
    # assert archive file is deleted

    assert not list(Path(artifact_path).glob("*.tar.gz"))
    assert not list(Path(artifact_path).glob("*.zip"))
    assert not list(Path(artifact_path).glob("*.tar.xz"))
    assert not list(Path(artifact_path).glob("*.tar"))
    assert not list(Path(artifact_path).glob("*.tar.bz2"))
