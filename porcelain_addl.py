# porcelain.py -- Porcelain-like layer on top of Dulwich
# Copyright (C) 2023 Kevin B. Hendricks, Stratford Ontario Canada
# Copyright (C) 2013 Jelmer Vernooij <jelmer@jelmer.uk>
#
# Dulwich is dual-licensed under the Apache License, Version 2.0 and the GNU
# General Public License as public by the Free Software Foundation; version 2.0
# or (at your option) any later version. You can redistribute it and/or
# modify it under the terms of either of these two licenses.
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# You should have received a copy of the licenses; if not, see
# <http://www.gnu.org/licenses/> for a copy of the GNU General Public License
# and <http://www.apache.org/licenses/LICENSE-2.0> for a copy of the Apache
# License, Version 2.0.
#

import datetime
import os
import posixpath
import stat
import sys
import time

from collections import namedtuple
from contextlib import closing, contextmanager
from io import BytesIO
from pathlib import Path
from typing import Optional, Tuple, Union

from dulwich.diff_tree import (
    CHANGE_ADD,
    CHANGE_COPY,
    CHANGE_DELETE,
    CHANGE_MODIFY,
    CHANGE_RENAME,
    RENAME_CHANGE_TYPES,
)
from dulwich.file import ensure_dir_exists
from dulwich.ignore import IgnoreFilterManager
from dulwich.index import (
    _fs_to_tree_path,
    blob_from_path_and_stat,
    build_file_from_blob,
    get_unstaged_changes,
    index_entry_from_stat,
    os_sep_bytes
)
from dulwich.object_store import iter_tree_contents, tree_lookup_path
from dulwich.objects import (
    Commit,
    Tag,
    format_timezone,
    parse_timezone,
    pretty_format_tree_entry,
)
from dulwich.objectspec import (
    parse_commit,
    parse_object,
    parse_ref,
    parse_reftuples,
    parse_tree,
    to_bytes,
)
from dulwich.patch import write_tree_diff
from patch_addl import (
    write_tree_workingdir_diff,
    write_tree_index_diff,
    write_index_workingdir_diff
    )
from dulwich.refs import (
    LOCAL_BRANCH_PREFIX,
    LOCAL_REMOTE_PREFIX,
    LOCAL_TAG_PREFIX,
    _import_remote_refs,
)
from dulwich.repo import BaseRepo, Repo
from dulwich.porcelain import (
    open_repo_closing,
    default_bytes_out_stream,
    default_bytes_err_stream,
    DEFAULT_ENCODING
)

from graph_fixed import (
    can_fast_forward,
    find_merge_base,
    find_octopus_base
)

from merge_addl import (
    merge,
    MergeResults,
    MergeConflict
)

def diff_tree(repo, old_tree, new_tree, outstream=default_bytes_out_stream):
    """Compares the content and mode of blobs found via two tree objects.

    Args:
      repo: Path to repository
      old_tree: Id of old tree
      new_tree: Id of new tree
      outstream: Stream to write to
    """
    with open_repo_closing(repo) as r:
        # write_tree_diff(outstream, r.object_store, old_tree, new_tree)
        diffstream = BytesIO()
        write_tree_diff(diffstream, r.object_store, old_tree, new_tree)
        diffstream.seek(0)
        # write bytes directly to output stream under python 2.7 and 3.x
        outstream.flush()
        getattr(outstream, 'buffer', outstream).write(diffstream.getvalue())
        outstream.flush()


def _walk_working_dir_paths(frompath, basepath, prune_dirnames=None):
    """Get path, is_dir for files in working dir from frompath.

    Args:
      frompath: Path to begin walk
      basepath: Path to compare to
      prune_dirnames: Optional callback to prune dirnames during os.walk
        dirnames will be set to result of prune_dirnames(dirpath, dirnames)
    """
    # Note os.walk will return bytes if passed in a bytes path
    # otherwise str
    _SKIP = '.git'
    if isinstance(frompath, bytes):
        _SKIP = b'.git'

    for dirpath, dirnames, filenames in os.walk(frompath):
        # Skip .git and below.
        if _SKIP in dirnames:
            dirnames.remove(_SKIP)
            if dirpath != basepath:
                continue

        if _SKIP in filenames:
            filenames.remove(_SKIP)
            if dirpath != basepath:
                continue

        if dirpath != frompath:
            yield dirpath, True

        for filename in filenames:
            filepath = os.path.join(dirpath, filename)
            yield filepath, False

        if prune_dirnames:
            dirnames[:] = prune_dirnames(dirpath, dirnames)


def branch_merge(repo, committishs, file_merger=None, update_working_dir=True):
    """Perform merge of set of commits representing branch heads
    Args:
      repo:               Repository in which the commits live
      committishs:        List of committish entries
      file_merger:        routine to perform the 3-way merge
      update_working_dir: write change entries to current working directory
    Returns:
      MergeResults object
    """
    with open_repo_closing(repo) as r:
        commits = [parse_commit(r, committish).id
                   for committish in committishs]
        mrg_results = merge(r, commits, rename_detector=None, file_merger=file_merger, update_working_dir=update_working_dir)
        return mrg_results


def merge_base(repo, committishs, all=False, octopus=False):
    """Find the merge base to use for a set of commits.
    Args:
      repo: Repository path in which the commits live
      committishs: List of committish entries
      all: if true return multiple results as a list
      octopus: if true find LCA of commits considered simultaneously
    Returns:
      common merge commit id or None (or list of all if all true)
    """
    with open_repo_closing(repo) as r:
        commits = [parse_commit(r, committish).id
                   for committish in committishs]
        if octopus:
            lcas = find_octopus_base(r, commits)
        else:
            lcas = find_merge_base(r, commits)
        if all:
            return lcas
        if lcas:
            return lcas[0]
        return None


def merge_base_is_ancestor(repo, committish_A, committish_B):
    """Test if committish_A is ancestor of committich_B
    Args:
      repo: Repository path in which the commits live
      committish_A, committish_B: commits to test
    Returns:
      True if commitish_A is ancestor of committish_B False otherwise
    """
    with open_repo_closing(repo) as r:
        commit_A = parse_commit(r, committish_A).id
        commit_B = parse_commit(r, committish_B).id
        lcas = find_merge_base(r, [commit_A, commit_B])
        return lcas == [commit_A]


def diff(repo, committish1=None,
         committish2=None,
         cached=False,
         outstream=sys.stdout):
    """Compares various commits, the index, and/or the working directory
    Args:
      repo: Path to repository
      committish1: commit to use as base for comparison
      committish2: commit to use as target for comparison
      cached: if true use the index (staged==cached) as target
      outstream: Stream to write to
    Returns:
       diff(repo):
           returns comparison of index to working directory
       diff(repo, commitish1):
           returns comparison of commit1 to working directory
       diff(repo, committish1, cached=True):
           returns comparison of commit1 to the index (staged == cached)
       diff(repo, committish1, committish2):
           returns the changes in commit2 relative to commit1
    """
    with open_repo_closing(repo) as r:

        diffstream = BytesIO()

        if committish1 and committish2:
            # diff of commit1 to commit2
            commit1 = parse_commit(r, committish1).id
            commit2 = parse_commit(r, committish2).id
            tree1 = r.object_store[commit1].tree
            tree2 = r.object_store[commit2].tree
            write_tree_diff(diffstream, r.object_store, tree1, tree2)

        elif committish1 and cached:
            # diff of commit1 to the index (staged=cached)
            commit = parse_commit(r, committish1).id
            tree = r.object_store[commit].tree
            index = r.open_index()
            write_tree_index_diff(diffstream, r.object_store, tree, index)

        else:
            # remaining types involve the working directory so
            # build up file name list of non-ignored files in working
            # directory as tree paths (bytes)
            names = []
            wkdir = os.fsencode(r.path)
            ignore_manager = IgnoreFilterManager.from_repo(r)
            for apath, isdir in _walk_working_dir_paths(wkdir, wkdir):
                file_path = os.path.relpath(apath, wkdir)
                if os_sep_bytes != b'/':
                    tree_path = file_path.replace(os_sep_bytes, b'/')
                else:
                    tree_path = file_path
                # ignore manger only works with unicode paths
                ignored = ignore_manager.is_ignored(os.fsdecode(tree_path))
                if not isdir and not ignored:
                    names.append(tree_path)

            # set up a normalizer callback for checkin
            # to handle line ending conversion for files in
            # the working directory
            normalizer = r.get_blob_normalizer()
            filter_callback = normalizer.checkin_normalize

            if committish1 and not cached:
                # diff of commit1 to the working directory
                commit = parse_commit(r, committish1).id
                tree = r.object_store[commit].tree
                write_tree_workingdir_diff(diffstream, r.object_store,
                                           tree, names, filter_callback)
            else:
                # diff of the index to the working directory
                index = r.open_index()
                write_index_workingdir_diff(diffstream, r.object_store,
                                            index, names, filter_callback)

        # since encoding of diff of source files is not known
        # write bytes directly to output stream under python 2.7 and 3.x
        diffstream.seek(0)
        outstream.flush()
        getattr(outstream, 'buffer', outstream).write(diffstream.getvalue())
        outstream.flush()
        return
