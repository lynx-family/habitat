import os

from core.components.solution import load_entries_cache_from_git
from core.main import main
from core.settings import GLOBAL_CACHE_DIR
from core.utils import create_temp_dir
from utils import run_with_custom_argv


def test_clean_temp_dir(default_repo):
    create_temp_dir(default_repo)

    temp_dirs = []
    for file in os.listdir(default_repo):
        if file.startswith('TEMP-'):
            temp_dirs.append(file)

    assert temp_dirs
    for temp_dir in temp_dirs:
        assert os.path.exists(os.path.join(default_repo, temp_dir))

    run_with_custom_argv(main, [
        'hab', 'clean', default_repo
    ])

    for temp_dir in temp_dirs:
        assert not os.path.exists(temp_dir)


def test_clean_deps(default_repo):
    run_with_custom_argv(main, [
        'hab', 'sync', default_repo, '--main'
    ])

    assert load_entries_cache_from_git(default_repo) is not None
    run_with_custom_argv(main, [
        'hab', 'clean', '-d', default_repo
    ])

    assert load_entries_cache_from_git(default_repo) is None


def test_clean_cache(default_repo):
    run_with_custom_argv(main, [
        'hab', 'sync', default_repo, '--main',
    ])

    assert os.path.exists(GLOBAL_CACHE_DIR)
    run_with_custom_argv(main, [
        'hab', 'clean', '-c', default_repo
    ])
    assert not os.path.exists(os.path.join(GLOBAL_CACHE_DIR, 'git'))
