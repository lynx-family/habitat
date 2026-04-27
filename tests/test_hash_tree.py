from pathlib import Path

from core.common.hash_tree import HashTree
from utils import generate_random_string


def test_merkle_tree(tmp_path: Path):
    root = tmp_path

    # directories
    sub_dir_a = tmp_path / "sub_dir_a"
    sub_dir_a_1 = tmp_path / "sub_dir_a" / "1"
    sub_dir_a_2 = tmp_path / "sub_dir_a" / "2"
    sub_dir_b = tmp_path / "sub_dir_b"

    for dir in [sub_dir_a, sub_dir_a_1, sub_dir_a_2, sub_dir_b]:
        dir.mkdir(parents=True, exist_ok=True)

    # files
    sub_dir_a_hello = sub_dir_a / "hello"
    sub_dir_a_world = sub_dir_a / "world"
    sub_dir_a_1_foo = sub_dir_a_1 / "foo"
    sub_dir_a_1_bar = sub_dir_a_1 / "bar"
    sub_dir_a_1_2k = sub_dir_a_1 / "2k"

    for file in [
        sub_dir_a_hello,
        sub_dir_a_world,
        sub_dir_a_1_foo,
        sub_dir_a_1_bar,
        sub_dir_a_1_2k,
    ]:
        file.write_text(generate_random_string())

    # symlink
    sub_dir_b_broken_link = sub_dir_b / "broken_link"
    sub_dir_b_broken_link.symlink_to(Path("non-existent"))
    sub_dir_b_link = sub_dir_b / "link"
    sub_dir_b_link.symlink_to(sub_dir_a_1_2k)

    tree = HashTree()
    original_fast_hash = tree.get_hex_digest(root, full_hash=False)
    original_full_hash = tree.get_hex_digest(root, full_hash=True)

    # modify sub_dir_a_1_2k, full hash should differ.
    original_2k_content = sub_dir_a_1_2k.read_text()
    sub_dir_a_1_2k.write_text(generate_random_string())
    fast_hash_1 = tree.get_hex_digest(root, full_hash=False)
    full_hash_1 = tree.get_hex_digest(root, full_hash=True)
    assert fast_hash_1 == original_fast_hash
    assert full_hash_1 != original_full_hash
    sub_dir_a_1_2k.write_text(original_2k_content)

    # remove sub_dir_a_2, fast hash should differ.
    sub_dir_a_2.rmdir()
    fast_hash_2 = tree.get_hex_digest(root, full_hash=False)
    assert fast_hash_2 != original_fast_hash
    sub_dir_a_2.mkdir()

    # modify link, fast hash should differ.
    sub_dir_b_link.unlink()
    sub_dir_b_link.symlink_to(sub_dir_b_broken_link)
    fast_hash_3 = tree.get_hex_digest(root, full_hash=False)
    assert fast_hash_3 != original_fast_hash
    sub_dir_b_link.unlink()
    sub_dir_b_link.symlink_to(sub_dir_a_1_2k)

    # all changes recoverd, all hash should be the same.
    final_fast_hash = tree.get_hex_digest(root, full_hash=False)
    final_full_hash = tree.get_hex_digest(root, full_hash=True)

    assert final_fast_hash == original_fast_hash
    assert final_full_hash == original_full_hash
