import os
import shlex
import subprocess

import pytest

from utils import create_test_binary_resource, generate_habitat_config_file, make_change_in_repo

pytest_plugins = ("pytest_httpserver",)


@pytest.fixture(name='default_repo')
def fixture_default_repo(tmp_path):
    """
    The fixture includes a main repo with two dependencies: a git dependency and an action dependency.
    """
    subprocess.run(shlex.split('git init main --initial-branch=master'), cwd=tmp_path, check=True)
    subprocess.run(shlex.split('git init git-dependency --initial-branch=master'), cwd=tmp_path, check=True)

    make_change_in_repo(
        os.path.join(tmp_path, 'git-dependency'),
        'hello.py',
        'print("hello")',
        'add hello.py',
        'w'
    )

    solutions = [
        {
            'name': '.',
            'deps_file': 'DEPS',
            'url': f'file://{tmp_path}/main/.git',
            'branch': 'master'
        }
    ]

    deps = {
        'git-dependency': {
            'type': 'git',
            'url': f'file://{tmp_path}/git-dependency/.git',
            'branch': 'master'
        },
        'action': {
            'type': 'action',
            'commands': [
                'ls -al',
                'python -c "import platform; print(platform.platform())"'
            ],
        }
    }

    make_change_in_repo(
        os.path.join(tmp_path, 'main'),
        '.habitat',
        generate_habitat_config_file('solutions', solutions),
        'add .habitat',
        'w'
    )

    make_change_in_repo(
        os.path.join(tmp_path, 'main'),
        'DEPS',
        generate_habitat_config_file('deps', deps),
        'add DEPS',
        'w'
    )
    return os.path.join(tmp_path, 'main')


@pytest.fixture(name='lfs_repo')
def fixture_lfs_repo(default_repo):
    """
    The fixture includes a main repo and a sub repo tracked by lfs, returns the main repo path
    and the lfs tracked binary's sha256.
    """
    temp_path = os.path.dirname(default_repo)
    remote_path = os.path.join(temp_path, 'remote')
    os.makedirs(remote_path, exist_ok=True)

    subprocess.run(shlex.split('git init lfs --initial-branch=master'), cwd=remote_path, check=True)

    # we use temp_path/remote/lfs as a lfs server, use temp_path/lfs to push binary file to lfs server.
    subprocess.run(shlex.split(f'git clone file://{remote_path}/lfs/.git'), cwd=temp_path, check=True)
    temp_lfs_repo_path = os.path.join(temp_path, 'lfs')
    binary, sha256 = create_test_binary_resource()
    with open(os.path.join(temp_lfs_repo_path, 'binary'), 'wb') as f:
        f.write(binary)

    subprocess.run(shlex.split('git checkout -b main'), cwd=temp_lfs_repo_path, check=True)
    subprocess.run(shlex.split("git lfs track '/binary'"), cwd=temp_lfs_repo_path, check=True)
    subprocess.run(shlex.split('git add .'), cwd=temp_lfs_repo_path, check=True)
    subprocess.run(shlex.split('git commit -m "track binary with git lfs"'), cwd=temp_lfs_repo_path, check=True)
    subprocess.run(shlex.split('git push origin main'), cwd=temp_lfs_repo_path, check=True)

    deps = {
        'lfs': {
            'type': 'git',
            'url': f'file://{remote_path}/lfs/.git',
            'branch': 'main',
            'enable_lfs': True
        }
    }

    make_change_in_repo(
        default_repo,
        'DEPS',
        generate_habitat_config_file('deps', deps),
        'add repo tracked by lfs',
        'w'
    )

    return default_repo, sha256
