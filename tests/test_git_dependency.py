import asyncio
import os
import subprocess
from argparse import Namespace

from core.components.git_dependency import GitDependency


def test_fetch_by_tag(tmp_path):
    # Prepare local git repository
    os.chdir(tmp_path)
    subprocess.check_call(["git", "init", "git"])
    os.chdir("git")
    with open("test", "w") as f:
        f.write("test")
    subprocess.check_call(["git", "add", "."])
    subprocess.check_call(["git", "commit", "-m", "test"])
    subprocess.check_call(["git", "tag", "v0.0.1"])

    os.chdir("../..")
    dep = GitDependency(
        os.path.join(tmp_path, "target_repo"),
        {
            "name": "target_repo",
            "type": "git",
            "url": f"file://{tmp_path}/git/.git",
            "tag": "v0.0.1",
        },
    )

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    options = Namespace(
        force=False, git_auth=None, clean=False, raw=False, disable_cache=True
    )
    loop.run_until_complete(dep.fetch(tmp_path, options))
