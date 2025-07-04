import asyncio
import hashlib
import os
import subprocess
import sys
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile


def run_with_custom_argv(func, argv):
    with patch.object(sys, "argv", argv):
        func()


def async_run_with_custom_argv(func, argv):
    with patch.object(sys, "argv", argv):
        asyncio.run(func())


def create_test_binary_resource(
    size: int = 1 * 1024 * 1024, return_bytes_only: bool = False
):
    c = os.urandom(size)
    h = hashlib.sha256(c).hexdigest()
    if not return_bytes_only:
        return c, h
    return c


def create_zip_file():
    io = BytesIO()
    with ZipFile(io, "w") as f:
        f.writestr("hello.py", 'print("hello")')

    return io.getvalue(), len(io.getvalue()), hashlib.sha256(io.getvalue()).hexdigest()


def make_change_in_repo(
    repo_dir: str, file_path: str, content: str, commit_message: str, mode: str
):
    with open(os.path.join(repo_dir, file_path), mode) as f:
        f.write(content)
    subprocess.check_call(["git", "add", file_path], cwd=repo_dir)
    subprocess.check_call(["git", "commit", "-m", f'"{commit_message}"'], cwd=repo_dir)
    commit_id = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo_dir)
        .decode()
        .strip()
    )
    return commit_id


def generate_habitat_config_file(config_name: str, config):
    return f"{config_name}={str(config)}"
