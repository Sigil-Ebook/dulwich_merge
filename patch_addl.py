# patch.py -- For dealing with packed-style patches.
# Copyright (C) 2023 Kevin B. Hendricks, Stratford Ontario Canada
# Copyright (C) 2009-2013 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Classes for dealing with git am-style patches.

These patches are basically unified diffs with some extra metadata tacked
on.
"""

import time
import os
import sys

from index_addl import changes_from_workingdir

from dulwich.index import (
    changes_from_tree,
    blob_from_path_and_stat,
    os_sep_bytes
)

from dulwich.patch import (
    is_binary,
    unified_diff,
    shortid,
    patch_filename
)

def _write_diff(f, a, b):
    (name1, mode1, sha1, content1) = a
    (name2, mode2, sha2, content2) = b
    if not name2:
        name2 = name1
    if not name1:
        name1 = name2
    old_path = patch_filename(name1, b"a")
    new_path = patch_filename(name2, b"b")
    f.write(b"diff --git " + old_path + b" " + new_path + b"\n")
    f.write(b"index " + shortid(sha1) + b".." + shortid(sha2) + b"\n")
    if is_binary(content1) or is_binary(content2):
        f.write(b"Binary files "
                + old_path
                + b" and "
                + new_path
                + b" differ\n")
    else:
        f.writelines(unified_diff(content1.splitlines(True),
                                  content2.splitlines(True),
                                  old_path,
                                  new_path))



def write_tree_workingdir_diff(f, store, tree, names,
                               filter_callback=None,
                               diff_binary=False):
    """Write diff of tree against current working dir
    Args:
      f: File-like object to write to.
      tree: tree id for base of comparison
      names: list of working directory relative file paths (bytes only)
      diff_binary: Whether to diff files even if they
        are considered binary files by is_binary().
    """

    entry_info = {}

    def lookup_entry(name):
        if name in entry_info:
            blob, fmode = entry_info[name]
            return (blob.id, fmode)
        return (None, None)

    # convert tree_paths that represent files in working dir
    # to an equivalent temp blob mode and store it
    # This should properly handle checkin normalization
    # which is required to make diffs work properly
    for name in names:
        filepath = name
        if os_sep_bytes != b'/':
            filepath = name.replace(b'/', os_sep_bytes)
        stat = os.stat(filepath)
        fmode = stat.st_mode
        blob = blob_from_path_and_stat(filepath, stat)
        if filter_callback:
            blob = filter_callback(blob, name)
        entry_info[name] = (blob, fmode)

    for change_entry in changes_from_tree(names, lookup_entry, store, tree):
        (name1, name2), (mode1, mode2), (sha1, sha2) = change_entry
        content1 = b''
        content2 = b''
        if name2:
            if name2 in entry_info:
                blob, fmode = entry_info[name2]
                content2 = blob.as_raw_string()
        if name1:
            content1 = store[sha1].as_raw_string()
        _write_diff(f, (name1, mode1, sha1, content1),
                       (name2, mode2, sha2, content2))



def write_tree_index_diff(f, store, tree, index, diff_binary=False):
    """Write diff of tree against current index
    Args:
      f: File-like object to write to.
      tree: tree id for base of comparison
      index: index (Index instance)
      diff_binary: Whether to diff files even if they
        are considered binary files by is_binary().
    """
    for change_entry in index.changes_from_tree(store, tree):
        (name1, name2), (mode1, mode2), (sha1, sha2) = change_entry
        content1 = b''
        content2 = b''
        if name2:
            content2 = store[sha2].as_raw_string()
        if name1:
            content1 = store[sha1].as_raw_string()
        _write_diff(f, (name1, mode1, sha1, content1),
                       (name2, mode2, sha2, content2))



def write_index_workingdir_diff(f, store, index, names,
                                filter_callback=None,
                                diff_binary=False):
    """Write diff of index against current working dir
    Args:
      f: File-like object to write to.
      index: Index object for base of comparison
      names: list of working directory relative file paths (bytes)
      diff_binary: Whether to diff files even if they
        are considered binary files by is_binary().
    """

    entry_info = {}

    def lookup_entry(name):
        if name in entry_info:
            blob, fmode = entry_info[name]
            return (blob.id, fmode)
        return (None, None)

    # convert tree_paths that represent files in working dir
    # to an equivalent temp blob mode and store it
    # This should properly handle checkin normalization
    # which is required to make diffs work properly
    for name in names:
        filepath = name
        if os_sep_bytes != b'/':
            filepath = name.replace(b'/', os_sep_bytes)
        stat = os.stat(filepath)
        fmode = stat.st_mode
        blob = blob_from_path_and_stat(filepath, stat)
        if filter_callback:
            blob = filter_callback(blob, name)
        entry_info[name] = (blob, fmode)

    for change_entry in changes_from_workingdir(names, lookup_entry,
                                                store, index):
        (name1, name2), (mode1, mode2), (sha1, sha2) = change_entry
        content1 = b''
        content2 = b''
        if name2:
            if name2 in entry_info:
                blob, fmode = entry_info[name2]
                content2 = blob.as_raw_string()
        if name1:
            content1 = store[sha1].as_raw_string()
        _write_diff(f, (name1, mode1, sha1, content1),
                       (name2, mode2, sha2, content2))
