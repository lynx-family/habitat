import hashlib
import json
import os.path
import subprocess
from unittest.mock import patch

from core.components.solution import load_entries_cache_from_git, store_entries_cache_to_git
from core.exceptions import HabitatException
from core.main import main
from core.utils import rmtree
from utils import create_zip_file, generate_habitat_config_file, make_change_in_repo, run_with_custom_argv


def test_sync_local_cache(default_repo):
    run_with_custom_argv(main, ['hab', 'sync', default_repo, '--main'])

    # re-sync to use local cache
    # TODO(wangjianliang): check if entries cache takes effect
    run_with_custom_argv(main, ['hab', 'sync', default_repo, '--main'])


def test_sync_disable_cache(default_repo):
    run_with_custom_argv(main, [
        'hab', 'sync', default_repo, '--main', '--disable-cache',
    ])


def test_store_and_load_entries_cache(default_repo):
    os.chdir(default_repo)
    test_entries = {
        "entries": {
            ".": "git@host.example.com:namespace/monorepo.git@",
            "example/branch": "git@host.example.com:namespace/foo.git@master",
            "example/commit": "git@host.example.com:namespace/bar.git@e0caee08e5f09b374a27a676d04978c81fcb1928",
            "example-action": "@",
        },
        "hash": "e827dc0158379e88168b286792443103"
    }

    store_entries_cache_to_git(test_entries)
    entries = load_entries_cache_from_git()

    assert test_entries == entries


def test_sync_recursively_duplicated_source():
    """
    Independent repositories:
        main(git 1)
         └── sub2(git 2 revision 1)

        sub1(git 3)
         ├── subsub1
         └── subsub2(git 2 revision 2)

    Integrated repositories:
        main(git 1)
         ├── sub1(git 3)
         │    ├── subsub1
         │    └── subsub2 -> ../sub2
         └── sub2(git 2 revision 1)
    """

    temp_dir = test_sync_recursively_duplicated_source.__name__
    cwd = os.path.join(os.getcwd(), temp_dir)
    rmtree(temp_dir, ignore_errors=True)

    # Prepare git repository 1
    repos_dir = os.path.join(temp_dir, 'repos')
    os.makedirs(repos_dir)
    os.chdir(repos_dir)
    subprocess.check_call(['git', 'init', 'git1', '--initial-branch=master'])
    os.chdir('git1')  # repos -> repos/git1
    # Prepare DEPS file
    deps = {
        "sub1": {
            "type": "solution",
            "url": f"file://{cwd}/repos/git3/.git",
            "branch": "master",
        },
        "sub2": {
            "type": "git",
            "url": f"file://{cwd}/repos/git2/.git",
            "branch": "master"
        }
    }
    with open('DEPS', 'w') as f:
        f.write(f'deps = {json.dumps(deps)}')
    subprocess.check_call(['git', 'add', '.'])
    subprocess.check_call(['git', 'commit', '-m', 'test'])

    # Prepare git repository 2
    os.chdir('..')  # repos/git1 -> repos
    subprocess.check_call(['git', 'init', 'git2', '--initial-branch=master'])
    os.chdir('git2')  # repos -> repos/git2
    # Prepare DEPS file
    with open('test', 'w') as f:
        f.write('test')
    subprocess.check_call(['git', 'add', '.'])
    subprocess.check_call(['git', 'commit', '-m', 'test'])

    # Prepare git repository 3
    os.chdir('..')  # repos/git2 -> repos
    subprocess.check_call(['git', 'init', 'git3', '--initial-branch=master'])
    os.chdir('git3')  # repos -> repos/git3
    os.mkdir('subsub1')
    with open(os.path.join('subsub1', 'test'), 'w') as f:
        f.write('test')
    # Prepare DEPS file
    deps = {
        "subsub2": {
            "type": "git",
            "url": f"file://{cwd}/repos/git2/.git",
            "branch": "master",
        }
    }
    with open('DEPS', 'w') as f:
        f.write(f'deps = {deps}')
    subprocess.check_call(['git', 'add', '.'])
    subprocess.check_call(['git', 'commit', '-m', 'test'])

    # Test sync
    os.chdir('../..')  # repos/git3 -> .
    run_with_custom_argv(main, [
        'hab', 'config', f'file://{cwd}/repos/git1/.git', 'main', '-b', 'master'
    ])

    run_with_custom_argv(main, [
        'hab', 'sync', 'main', '--main', '--disable-cache',
    ])

    # Check result
    assert os.path.isdir(os.path.join('main', 'sub1', 'subsub1'))
    assert os.path.islink(os.path.join('main', 'sub1', 'subsub2'))
    assert os.path.realpath(os.path.join('main', 'sub1', 'subsub2')) == os.path.realpath(os.path.join('main', 'sub2'))
    assert os.path.isdir(os.path.join('main', 'sub2', '.git'))

    os.chdir('..')
    rmtree(temp_dir, ignore_errors=True)


def test_sync_recursively_targets_conflicts():
    """
    Independent repositories:
        main(git 1)
         └── sub2(git 2)

        sub1(git 3)
         ├── subsub1
         └── ../sub2(git 4)

    Integrated repositories:
        main(git 1)
         ├── sub1(git 3)
         │    └── subsub1
         └── sub2(git 2)
    """

    temp_dir = test_sync_recursively_targets_conflicts.__name__
    cwd = os.path.join(os.getcwd(), temp_dir)
    rmtree(temp_dir, ignore_errors=True)

    # Prepare git repository 1
    repos_dir = os.path.join(temp_dir, 'repos')
    os.makedirs(repos_dir)
    os.chdir(repos_dir)
    subprocess.check_call(['git', 'init', 'git1', '--initial-branch=master'])
    os.chdir('git1')  # repos -> repos/git1
    # Prepare DEPS file
    deps = {
        "sub1": {
            "type": "solution",
            "url": f"file://{cwd}/repos/git3/.git",
            "branch": "master",
        },
        "sub2": {
            "type": "git",
            "url": f"file://{cwd}/repos/git2/.git",
            "branch": "master"
        }
    }
    with open('DEPS', 'w') as f:
        f.write(f'deps = {json.dumps(deps)}')
    subprocess.check_call(['git', 'add', '.'])
    subprocess.check_call(['git', 'commit', '-m', 'test'])

    # Prepare git repository 2
    os.chdir('..')  # repos/git1 -> repos
    subprocess.check_call(['git', 'init', 'git2', '--initial-branch=master'])
    os.chdir('git2')  # repos -> repos/git2
    # Prepare DEPS file
    with open('test', 'w') as f:
        f.write('test')
    subprocess.check_call(['git', 'add', '.'])
    subprocess.check_call(['git', 'commit', '-m', 'test'])

    # Prepare git repository 3
    os.chdir('..')  # repos/git2 -> repos
    subprocess.check_call(['git', 'init', 'git3', '--initial-branch=master'])
    os.chdir('git3')  # repos -> repos/git3
    os.mkdir('subsub1')
    with open(os.path.join('subsub1', 'test'), 'w') as f:
        f.write('test')
    # Prepare DEPS file
    deps = {
        "../sub1": {
            "type": "git",
            "url": f"file://{cwd}/repos/git4/.git",
            "branch": "master",
        }
    }
    with open('DEPS', 'w') as f:
        f.write(f'deps = {deps}')
    subprocess.check_call(['git', 'add', '.'])
    subprocess.check_call(['git', 'commit', '-m', 'test'])

    # Test sync
    os.chdir('../..')  # repos/git3 -> .
    run_with_custom_argv(main, [
        'hab', 'config', f'file://{cwd}/repos/git1/.git', 'main', '-b', 'master'
    ])

    run_with_custom_argv(main, [
        'hab', 'sync', 'main', '--main', '--disable-cache',
    ])

    # Check result
    assert os.path.isdir(os.path.join('main', 'sub1', 'subsub1'))
    assert os.path.isdir(os.path.join('main', 'sub2', '.git'))

    os.chdir('..')
    rmtree(temp_dir, ignore_errors=True)


def disabled_test_sync_http_dependency(httpserver, default_repo):
    # create a zip archive
    data, size, sha256 = create_zip_file()
    httpserver.expect_request(uri='/download/binary.zip', method='HEAD').respond_with_data(
        status=200,
        headers={
            'Content-Length': str(size),
            'Accept-Ranges': 'bytes',
        },
        response_data=b''
    )
    httpserver.expect_request(uri='/download/binary.zip', method='GET').respond_with_data(
        status=200,
        response_data=data
    )

    deps = {
        'http': {
            'type': 'http',
            'url': httpserver.url_for('/download/binary.zip'),
            'sha256': sha256
        }
    }

    make_change_in_repo(
        default_repo,
        'DEPS',
        generate_habitat_config_file('deps', deps),
        'add http dependency',
        'w'
    )

    os.chdir(default_repo)
    run_with_custom_argv(main, ['hab', 'sync', '.'])

    file_path = os.path.join(default_repo, 'http', 'hello.py')
    assert os.path.exists(file_path)
    with open(file_path) as f:
        assert f.read() == 'print("hello")'


def test_sync_with_lfs(lfs_repo):
    # TODO(zouzhecheng): add a mock to check if git lfs pull was called
    main_repo_path, sha256 = lfs_repo
    os.chdir(main_repo_path)
    run_with_custom_argv(main, ['hab', 'sync', '.'])

    assert os.path.exists(os.path.join(main_repo_path, 'lfs', 'binary'))
    with open(os.path.join(main_repo_path, 'lfs', 'binary'), 'rb') as f:
        assert hashlib.sha256(f.read()).hexdigest() == sha256


def test_sync_target_only(tmp_path):
    os.chdir(tmp_path)
    cwd = os.getcwd()

    subprocess.check_call(['git', 'init', 'test-repo', '--initial-branch=master'])
    subprocess.check_call(['git', 'init', 'base-deps', '--initial-branch=master'])
    subprocess.check_call(['git', 'init', 'android-deps', '--initial-branch=master'])
    solutions = [
        {
            'name': '.',
            'deps_file': 'DEPS',
            'target_deps_files': {
                'android': 'DEPS.android',
            },
            'url': f'file://{cwd}/test-repo/.git',
            'branch': 'master'
        }
    ]
    deps = {
        'base': {
            'type': 'git',
            'url': f'file://{cwd}/base-deps/.git',
            'branch': 'master'
        }
    }
    android_deps = {
        'android': {
            'type': 'git',
            'url': f'file://{cwd}/android-deps/.git',
            'branch': 'master'
        }
    }
    make_change_in_repo(
        f'{cwd}/test-repo', '.habitat', generate_habitat_config_file('solutions', solutions),
        'add .habitat', 'w'
    )
    make_change_in_repo(
        f'{cwd}/test-repo', 'DEPS', generate_habitat_config_file('deps', deps), 'add base deps', 'w'
    )
    make_change_in_repo(
        f'{cwd}/test-repo', 'DEPS.android', generate_habitat_config_file('deps', android_deps), 'add android deps', 'w'
    )
    make_change_in_repo(
        f'{cwd}/base-deps', 'base.txt', 'i am base deps', 'add deps', 'w'
    )
    make_change_in_repo(
        f'{cwd}/android-deps', 'android.txt', 'i am android deps', 'add deps', 'w'
    )
    run_with_custom_argv(main, [
        'hab', 'sync', f'{cwd}/test-repo', '--target', 'android', '--target-only'
    ])
    assert not os.path.exists(f'{cwd}/test-repo/base')
    assert os.path.exists(f'{cwd}/test-repo/android/android.txt')

    run_with_custom_argv(main, [
        'hab', 'sync', f'{cwd}/test-repo', '--target-only'
    ])
    assert os.path.exists(f'{cwd}/test-repo/base')


def test_sync_git_repo_with_patches(tmp_path):
    os.chdir(tmp_path)
    cwd = os.getcwd()

    subprocess.check_call(['git', 'init', 'lib', '--initial-branch=master'])
    subprocess.check_call(['git', 'init', 'main', '--initial-branch=master'])

    first_commit = make_change_in_repo(
        f'{cwd}/lib',
        'hello.py',
        'print("hello, world.")',
        'add hello world',
        'w'
    )

    make_change_in_repo(
        f'{cwd}/lib',
        'hello.py',
        '\nprint("thanks!")',
        'add thanks',
        'a'
    )

    make_change_in_repo(
        f'{cwd}/lib',
        'hello.py',
        'print("done")',
        'done',
        'w'
    )

    make_change_in_repo(
        f'{cwd}/lib',
        'hello.py',
        'print("not yet")',
        'not yet',
        'w'
    )

    os.chdir('lib')
    subprocess.check_call(['git', 'format-patch', 'HEAD^^^'])
    os.chdir('..')

    os.chdir('main')
    os.makedirs('patches', exist_ok=True)
    os.makedirs('other_patches', exist_ok=True)
    os.chdir('..')
    subprocess.check_call(['mv', f'{cwd}/lib/0001-add-thanks.patch', f'{cwd}/main/patches/0001-add-thanks.patch'])
    subprocess.check_call(['mv', f'{cwd}/lib/0002-done.patch', f'{cwd}/main/patches/0002-done.patch'])
    subprocess.check_call(['mv', f'{cwd}/lib/0003-not-yet.patch', f'{cwd}/main/other_patches/0003-not-yet.patch'])
    os.chdir('main')
    subprocess.check_call(['git', 'add', '.'])
    subprocess.check_call(['git', 'commit', '-m', 'submit patches'])

    solutions = [
        {
            'name': '.',
            'deps_file': 'DEPS',
            'url': f'file://{cwd}/main/.git',
            'branch': 'master'
        }
    ]

    deps = {
        'lib': {
            'type': 'git',
            'url': f'file://{cwd}/lib/.git',
            'commit': first_commit,
            'patches': os.path.join(cwd, 'main', 'patches', '*.patch')
        },
        'lib-with-one-more-patch': {
            'type': 'git',
            'url': f'file://{cwd}/lib/.git',
            'commit': first_commit,
            'patches': [
                os.path.join(cwd, 'main', 'patches', '*.patch'),
                os.path.join(cwd, 'main', 'other_patches', '*.patch')
            ]
        }
    }

    make_change_in_repo(
        f'{cwd}/main',
        '.habitat',
        generate_habitat_config_file('solutions', solutions),
        'add .habitat',
        'w'
    )

    make_change_in_repo(
        f'{cwd}/main',
        'DEPS',
        generate_habitat_config_file('deps', deps),
        'add DEPS',
        'w'
    )

    run_with_custom_argv(main, ['hab', 'sync', '.'])

    assert os.path.exists(f'{cwd}/main/lib/hello.py')
    with open(f'{cwd}/main/lib/hello.py') as f:
        assert f.read() == 'print("done")'

    assert os.path.exists(f'{cwd}/main/lib-with-one-more-patch/hello.py')
    with open(f'{cwd}/main/lib-with-one-more-patch/hello.py') as f:
        assert f.read() == 'print("not yet")'


@patch('core.main.DEBUG', True)
def test_sync_dependency_with_cycled_requirement(tmp_path):
    os.chdir(tmp_path)
    cwd = os.getcwd()
    subprocess.check_call(['git', 'init', 'dep', '--initial-branch=master'])
    subprocess.check_call(['git', 'init', 'main-repo', '--initial-branch=master'])
    solutions = [
        {
            'name': '.',
            'deps_file': 'DEPS',
            'url': f'file://{cwd}/main-repo/.git',
            'branch': 'master'
        }
    ]
    deps = {
        'test_a': {
            'type': 'git',
            'url': f'file://{cwd}/dep/.git',
            'branch': 'master',
            'require': ['test_b']
        },
        'test_b': {
            'type': 'git',
            'url': f'file://{cwd}/dep/.git',
            'branch': 'master',
            'require': ['test_a']
        }
    }
    make_change_in_repo(
        f'{cwd}/main-repo', '.habitat', generate_habitat_config_file('solutions', solutions),
        'add .habitat', 'w'
    )
    make_change_in_repo(
        f'{cwd}/main-repo', 'DEPS', generate_habitat_config_file('deps', deps), 'add DEPS', 'w'
    )
    os.chdir('main-repo')
    try:
        run_with_custom_argv(main, ['hab', 'sync', '.'])
    except HabitatException as e:
        assert str(e) == "found a cicular dependency, please check test_b's requirement test_a."
