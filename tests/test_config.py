import os
import shlex
import subprocess

from core.main import main
from utils import run_with_custom_argv


def test_config_with_branch(tmp_path, default_repo):
    """
    default_repo (the remote of *test_config_repo*):
        main
         └── git-dependency

    test_config_repo
        test_config_repo (solutions url should point to main repo)
         └── git-dependency
    """
    subprocess.run(shlex.split('git init test-config --initial-branch=master'), cwd=tmp_path, check=True)
    test_config_repo_path = os.path.join(tmp_path, 'test-config')

    branch = 'master'
    run_with_custom_argv(main, [
        'hab', 'config', f'file://{default_repo}/.git', test_config_repo_path, '-b', branch
    ])

    run_with_custom_argv(main, [
        'hab', 'sync', test_config_repo_path, '--main'
    ])

    output = subprocess.check_output(['git', 'branch', '--show-current'], cwd=test_config_repo_path)
    assert branch == output.decode().strip()
