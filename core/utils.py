# Copyright 2024 The Lynx Authors. All rights reserved.
# Licensed under the Apache License Version 2.0 that can be found in the
# LICENSE file in the root directory of this source tree.

# Use of this source code is governed by a PSF-2.0 license
# that can be found in the THIRD-PARTY-LICENSE file in the
# root of the source tree.

import asyncio
import contextvars
import functools
import hashlib
import inspect
import logging
import math
import os
import pkgutil
import platform
import posixpath
import random
import re
import shlex
import shutil
import stat
import string
import subprocess
import sys
import traceback
from collections import defaultdict
from pathlib import Path
from zipfile import ZipFile

from core.exceptions import HabitatException
from core.settings import CACHE_DIR_PREFIX


async def to_thread(func, *args, **kwargs):
    """Asynchronously run function *func* in a separate thread.

    Any *args and **kwargs supplied for this function are directly passed
    to *func*. Also, the current :class:`contextvars.Context` is propagated,
    allowing context variables from the main thread to be accessed in the
    separate thread.

    Return a coroutine that can be awaited to get the eventual result of *func*.
    """
    loop = asyncio.get_running_loop()
    ctx = contextvars.copy_context()
    func_call = functools.partial(ctx.run, func, *args, **kwargs)
    return await loop.run_in_executor(None, func_call)


def match_paths(path, match_list: list):
    for p in match_list:
        if is_subdir(path, p):
            return True
    return False


def is_subdir(sub, parent):
    return os.path.commonpath([sub, parent]) == parent


def format_exception(e):
    et, ev, tb = sys.exc_info()
    msg = traceback.format_exception(et, ev, tb)
    return '\n'.join(msg)


async def async_check_call(*args, retry=0, **kwargs):
    remained_chances = retry + 1
    while True:
        try:
            remained_chances -= 1
            return await to_thread(check_call, *args, **kwargs)
        except subprocess.CalledProcessError as e:
            if remained_chances > 0:
                logging.warning(f'Got an exception {e} during running command {args} {kwargs}, retry')
            else:
                raise e


async def async_check_output(*args, retry=0, **kwargs):
    remained_chances = retry + 1
    while True:
        try:
            remained_chances -= 1
            return await to_thread(check_output, *args, **kwargs)
        except subprocess.CalledProcessError as e:
            if remained_chances > 0:
                logging.warning(f'Got an exception {e} during running command {args} {kwargs}, retry')
            else:
                raise e


def check_output(*args, **kwargs):
    logging.debug(f'Run command: {args[0]} (args: {args} kwargs: {kwargs}')
    output = subprocess.check_output(*args, **kwargs)
    logging.debug(f'Command {args[0]} end')
    return output


def check_call(*args, **kwargs):
    logging.debug(f'Run command: {args[0]} (args: {args} kwargs: {kwargs}')
    subprocess.check_call(*args, **kwargs)
    logging.debug(f'Command {args[0]} end')


def convert_git_url_to_http(url, auth=None):
    if url.startswith('git@'):
        url = '/'.join(url.rsplit(':', 1))
    url = url.replace("git@", 'https://')
    if auth:
        url = url.replace('://', f'://{auth}@')
    return url


def destinsrc(src, dst):
    src = os.path.abspath(src)
    dst = os.path.abspath(dst)
    if not src.endswith(os.path.sep):
        src += os.path.sep
    if not dst.endswith(os.path.sep):
        dst += os.path.sep
    return dst.startswith(src)


def samefile(src, dst):
    # Macintosh, Unix.
    if isinstance(src, os.DirEntry) and hasattr(os.path, 'samestat'):
        try:
            return os.path.samestat(src.stat(), os.stat(dst))
        except OSError:
            return False

    if hasattr(os.path, 'samefile'):
        try:
            return os.path.samefile(src, dst)
        except OSError:
            return False

    # All other platforms: check for same pathname.
    return os.path.normcase(os.path.abspath(src)) == os.path.normcase(os.path.abspath(dst))


def move(src, dst, copy_function=shutil.copy2):
    """Recursively move a file or directory to another location. This is
    similar to the Unix "mv" command. Return the file or directory's
    destination.

    If the destination is a directory or a symlink to a directory, the source
    is moved inside the directory. The destination path must not already
    exist.

    If the destination already exists but is not a directory, it may be
    overwritten depending on os.rename() semantics.

    If the destination is on our current filesystem, then rename() is used.
    Otherwise, src is copied to the destination and then removed. Symlinks are
    recreated under the new name if os.rename() fails because of cross
    filesystem renames.

    The optional `copy_function` argument is a callable that will be used
    to copy the source or it will be delegated to `copytree`.
    By default, copy2() is used, but any function that supports the same
    signature (like copy()) can be used.

    A lot more could be done here...  A look at a mv.c shows a lot of
    the issues this implementation glosses over.

    """
    real_dst = dst
    if os.path.isdir(dst):
        if samefile(src, dst):
            # We might be on a case insensitive filesystem,
            # perform the rename anyway.
            os.rename(src, dst)
            return

        # Using _basename instead of os.path.basename is important, as we must
        # ignore any trailing slash to avoid the basename returning ''
        real_dst = os.path.join(dst, os.path.basename(src))

        if os.path.exists(real_dst):
            raise Exception("Destination path '%s' already exists" % real_dst)
    try:
        os.rename(src, real_dst)
    except OSError:
        if os.path.islink(src):
            linkto = os.readlink(src)
            os.symlink(linkto, real_dst)
            os.unlink(src)
        elif os.path.isdir(src):
            if destinsrc(src, dst):
                raise Exception("Cannot move a directory '%s' into itself"
                                " '%s'." % (src, dst))

            def _is_immutable(f):
                st = f.stat() if isinstance(f, os.DirEntry) else os.stat(f)
                immutable_states = [stat.UF_IMMUTABLE, stat.SF_IMMUTABLE]
                return hasattr(st, 'st_flags') and st.st_flags in immutable_states

            if (_is_immutable(src) or (
                not os.access(src, os.W_OK) and os.listdir(src) and sys.platform == 'darwin'
            )):
                raise PermissionError("Cannot move the non-empty directory "
                                      "'%s': Lacking write permission to '%s'."
                                      % (src, src))
            shutil.copytree(src, real_dst, copy_function=copy_function,
                            symlinks=True)
            rmtree(src)
        else:
            copy_function(src, real_dst)
            os.unlink(src)
    return real_dst


def rmtree(path, ignore_errors=False):
    while os.path.exists(path):
        try:
            shutil.rmtree(path, ignore_errors=ignore_errors)
        except PermissionError as e:
            error_file = e.filename
            if os.path.exists(error_file):
                os.chmod(error_file, stat.S_IWUSR)
                os.remove(error_file)


def convert_to_posix_path(path):
    return path.replace(os.sep, posixpath.sep) if os.sep != posixpath.sep else path


def get_head_commit_id(**kwargs):
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], **kwargs).decode().strip()


def get_full_commit_id(short_id, url):
    cmd = ["git", "ls-remote", url]
    output = subprocess.check_output(cmd, stderr=subprocess.STDOUT)
    for line in output.decode().splitlines():
        if line.startswith(short_id):
            return line.split()[0].strip()
    raise Exception(f'commit id {short_id} not found on remote')


def ignore_paths_in_git(root_dir: str, paths: list, ignore_errors=False):
    ignored_paths = []
    for path in paths:
        # ignore fetched files in parent repository
        if os.path.isabs(path):
            path = relative_path(root_dir, path)
            path = Path(path).as_posix()
        cmd = f'git check-ignore -q {path}'
        try:
            check_call(cmd, shell=True, cwd=root_dir, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError:
            logging.debug(f'path {path} will be ignored in main repository')
            ignored_paths.append('/' + path)

    try:
        git_dir = Path(root_dir) / Path('.git')
        if os.path.isfile(git_dir):
            with open(git_dir, 'r') as f:
                matches = re.match(r'gitdir: (.*)', f.read())
                if not matches:
                    logging.warning(f'unrecognized git dir {git_dir}')
                git_dir = matches.group(1).strip()
        exclude_file = Path(git_dir) / Path('info/exclude')
        if not os.path.exists(os.path.dirname(exclude_file)):
            os.makedirs(os.path.dirname(exclude_file))

        if os.path.exists(exclude_file):
            with open(exclude_file, 'r') as f:
                ignored_paths = set(ignored_paths + [line.strip() for line in f.readlines() if line.strip()])

        with open(exclude_file, 'w') as f:
            f.write('\n'.join(ignored_paths) + '\n')

    except Exception as e:
        if ignore_errors:
            logging.warning(e)
        else:
            raise e


def is_md5_hash(val) -> bool:
    return bool(re.match(r"^([a-fA-F\d]{32})$", val))


def relative_path(base, sub):
    common = os.path.commonpath([base, sub])
    return os.path.relpath(sub, common)


def get_md5_of_file(path):
    m = hashlib.md5()
    with open(path, 'rb') as f:
        while True:
            data = f.read(4096 * 1024)
            if not data:
                break
            m.update(data)

    return m.hexdigest()


def create_symlink(src_path, dst_path):
    # Create dst_path's parent path recursively is not exist,
    # or it will fail when creating symbolic link
    dst_parent_path = Path(dst_path).parent
    if not os.path.exists(dst_parent_path):
        os.makedirs(dst_parent_path)

    if os.path.exists(src_path):
        os.symlink(src_path, dst_path)
        logging.info(f'Symbolic link created from {dst_path} to {src_path}')


def match_patterns(target, patterns):
    combined = "(" + ")|(".join(patterns) + ")"
    if re.match(combined, target):
        return True
    return False


def is_git_url(url):
    return url.startswith(('git@', 'ssh://', 'https://', 'http://', 'file://'))


def is_http_url(url):
    return url.startswith(('https://', 'http://'))


def is_git_sha(revision):
    """Returns true if the given string is a valid hex-encoded sha"""
    return re.match('^[a-fA-F0-9]{6,40}$', revision) is not None


def random_string(size=8, chars=string.ascii_letters + string.digits):
    return ''.join(random.choice(chars) for _ in range(size))


def is_git_root(path):
    if not is_git_repo(path):
        return False

    return Path(git_root_dir(path)) == Path(path)


def is_bare_git_repo(path):
    if not os.path.exists(path):
        return False

    cmd = f'git -C {path} rev-parse --is-bare-repository'
    try:
        output = subprocess.check_output(cmd, shell=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError:
        return False
    return output.decode().strip() == 'true'


def is_git_repo(path):
    if not os.path.exists(path):
        return False
    cmd = f'git -C {path} rev-parse'
    try:
        check_output(cmd, shell=True, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError:
        return False
    else:
        return True


def git_root_dir(path=None):
    command = ['git', 'rev-parse', '--show-toplevel']
    p = subprocess.Popen(' '.join(command),
                         stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE,
                         shell=True, cwd=path)
    result, error = p.communicate()
    if p.returncode and error:
        raise HabitatException(
            'Error, can not get git root in path %s, '
            'make sure it is a git repo: %s' % (error.decode('utf-8'), path)
        )
    return Path(result.decode('utf-8').strip())


def find_classes(module, is_target=None, handle_error=None, recursive=True):
    classes = set()
    submodules = []
    if not inspect.ismodule(module):
        return classes
    for info, name, is_pkg in pkgutil.iter_modules(module.__path__):
        full_name = module.__name__ + '.' + name
        mod = sys.modules.get(full_name)
        if not mod:
            try:
                mod = info.find_module(full_name).load_module(full_name)
            except AttributeError:
                mod = info.find_spec(full_name).loader.load_module(full_name)
            except Exception as e:
                logging.debug(format_exception(e))
                if handle_error:
                    handle_error(e)
                else:
                    raise e
                continue
        if is_pkg and recursive:
            submodules.append(mod)
        else:
            classes = classes.union(
                [
                    c[1]
                    for c in inspect.getmembers(mod, inspect.isclass)
                    if ((is_target is None or is_target(c[1])) and c[1].__module__ == mod.__name__)
                ]
            )
    for m in submodules:
        classes = classes.union(find_classes(m, is_target=is_target, handle_error=handle_error, recursive=recursive))
    return classes


def create_temp_dir(root_dir=os.getcwd(), name=None):
    cache_dir = os.path.join(root_dir, f'{CACHE_DIR_PREFIX}{name + "-" if name else ""}{random_string()}')
    if platform.system() == 'Windows':
        os.mkdir(cache_dir, mode=stat.S_IWRITE)
    else:
        os.mkdir(cache_dir)
    return cache_dir


def clean_temp_dirs(root_dir=os.getcwd(), name=None):
    for path in Path(root_dir).glob(f'{CACHE_DIR_PREFIX}{name + "-" if name else ""}*'):
        shutil.rmtree(path, ignore_errors=True)


class Singleton(type):
    _instances = {}

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]


class ProgressBar:

    def __init__(self, total=100, title=""):
        self.total = total
        self.title = title
        self.current = 0
        self.update(0)

    def update(self, n=1):
        self.current += n
        percent = '{:.2%}'.format(self.current / self.total)
        sys.stdout.write('\r')
        sys.stdout.write('%s[%-50s] %s' % (self.title, '=' * int(math.floor(self.current * 50 / self.total)), percent))
        sys.stdout.flush()
        if self.current == self.total:
            sys.stdout.write('\n')


async def set_git_alternates(source_dir, objects_dir):
    info_dir = os.path.join(source_dir, '.git', 'objects', 'info')
    if not os.path.isdir(info_dir):
        raise HabitatException(f'directory {info_dir} does not exist')
    with open(os.path.join(info_dir, 'alternates'), 'w') as f:
        f.write(objects_dir)


async def clear_git_alternates(source_dir):
    alternates_file = os.path.join(source_dir, '.git', 'objects', 'info', 'alternates')
    if os.path.exists(alternates_file):
        cmd = 'git repack -a -d -q'
        await async_check_call(cmd, shell=True, cwd=source_dir)
        os.remove(alternates_file)


def is_git_repo_valid(source_dir):
    try:
        cmd = 'git status'
        check_output(cmd, shell=True, cwd=source_dir, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError:
        return False

    alternates_file = os.path.join(source_dir, '.git', 'objects', 'info', 'alternates')
    if not os.path.exists(alternates_file):
        return True
    with open(alternates_file, 'r') as f:
        for line in f.readlines():
            line = line.strip()
            if not line:
                continue
            if not os.path.exists(line):
                return False
    return True


def eval_deps(deps_file, target, root_dir):
    env = {"target": target, "root_dir": root_dir}
    if hasattr(deps_file, 'read'):
        exec(deps_file.read(), env)
    else:
        with open(deps_file, 'rb') as f:
            exec(f.read(), env)

    if 'deps' not in env:
        raise HabitatException(f'Can not find deps in file {deps_file}')
    return env["deps"]


def extract_zipfile(src: str, dst: str, paths: list):
    z = ZipFile(src, 'r')
    paths = [p.rstrip('/') for p in paths]
    for z_info in z.infolist():
        file, mode = z_info.filename, z_info.external_attr >> 16
        if paths and not match_paths(file, paths):
            continue
        else:
            file_path = os.path.join(dst, file)
            if stat.S_ISLNK(mode):
                target = Path(z.read(file).decode())
                symlink = Path(file_path)
                symlink.symlink_to(target)
            else:
                z.extract(file, dst)
                os.chmod(file_path, mode)


def extract_tarfile(src: str, dst: str, paths: list):
    if not os.path.exists(dst):
        os.makedirs(dst)
    tar = 'tar.exe' if platform.system().lower() == 'windows' else 'tar'
    subprocess.run(f"{tar} -xpf {src} -C {dst} {' '.join(paths)}", shell=True)


UNPACK_FORMAT_EXTENSIONS = {
    'zip': ['.aar', '.jar', '.zip'],
    'tar': ['.bz2', '.tbz2', '.gz', '.tgz', '.tar', '.xz', '.txz']
}

UNPACK_FORMAT_EXTRACTION = {
    'zip': extract_zipfile,
    'tar': extract_tarfile
}


def extract_archive(src: str, dst: str, paths: list):
    _, ext = os.path.splitext(src)
    archive_format = None
    for fmt, extensions in UNPACK_FORMAT_EXTENSIONS.items():
        if ext in extensions:
            archive_format = fmt

    if not archive_format:
        raise HabitatException(f'file {src} is not a supported archive format.')

    func = UNPACK_FORMAT_EXTRACTION.get(archive_format)
    func(src, dst, paths)
    os.remove(src)


def print_all_exception(e: BaseException):
    upper_exception = e.__cause__ or e.__context__
    logging.error(f'{type(e).__name__}: {e}')
    if upper_exception:
        print_all_exception(upper_exception)


def literally_replace(content: str, config):
    for token, value in config:
        content = content.replace(f'{{{token}}}', value)
    return content


async def is_git_user_set() -> bool:
    try:
        await async_check_output(
            shlex.split('git config user.name'), stderr=subprocess.STDOUT
        )
        await async_check_output(
            shlex.split('git config user.email'), stderr=subprocess.STDOUT
        )
    except subprocess.CalledProcessError:
        return False

    return True


class DependencyGraph:
    def __init__(self, deps: dict) -> None:
        self.node_requirements = defaultdict(list)
        for dep_name, dep in deps.items():
            requirements = getattr(dep, 'require', [])
            self.node_requirements[dep_name].extend(requirements)


def visit(graph, node, grey_nodes, black_nodes):
    # mark the current node as a grey node, indicates that its child has not been traversed.
    grey_nodes.add(node)

    for require in graph.node_requirements[node]:
        # cycle detected if current node needs a node that has been marked grey.
        if require in grey_nodes:
            raise HabitatException(
                f"found a cicular dependency, please check {node}'s requirement {require}."
            )

        # traverse the unvisited node.
        if require not in black_nodes:
            visit(graph, require, grey_nodes, black_nodes)

    # mark the current node as a black node, indicates that we don't need to visit it anymore.
    grey_nodes.remove(node)
    black_nodes.add(node)

    return grey_nodes, black_nodes


def cycle_detection(deps: dict):
    graph = DependencyGraph(deps)

    grey_nodes = set()
    black_nodes = set()

    for node in graph.node_requirements:
        if (node not in grey_nodes) and (node not in black_nodes):
            grey_nodes, black_nodes = visit(graph, node, grey_nodes, black_nodes)
