# merge.py -- Merge support in Dulwich
# Copyright (C) 2020 Jelmer Vernooij <jelmer@jelmer.uk>
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

"""Merge support."""
import os
import sys

from collections import namedtuple

from dulwich.index import build_file_from_blob

from dulwich.file import ensure_dir_exists

from dulwich.repo import Repo

from dulwich.objects import TreeEntry

from dulwich.diff_tree import (
    tree_changes,
    CHANGE_ADD,
    CHANGE_COPY,
    CHANGE_DELETE,
    CHANGE_MODIFY,
    CHANGE_RENAME,
    CHANGE_UNCHANGED,
    )

from dulwich.objects import Blob


from graph_fixed import find_merge_base


class MergeConflict(namedtuple(
        'MergeConflict',
        ['this_entry', 'other_entry', 'base_entry', 'message'])):
    """A merge conflict."""


def _merge_entry(new_path, object_store, this_entry,
                 other_entry, base_entry, file_merger):
    """ 3 way merge an entry """
    if file_merger is None:
        return MergeConflict(
            this_entry, other_entry,
            other_entry.old,
            'Conflict in %s but no file merger provided'
            % new_path)
    (merged_text, conflict_list) = file_merger(
        object_store[this_entry.sha].as_raw_string(),
        object_store[other_entry.sha].as_raw_string(),
        object_store[base_entry.sha].as_raw_string())
    merged_text_blob = Blob.from_string(merged_text)
    for (range_o, range_a, range_b ) in conflict_list:
        print("Chunk Conflict in: ", new_path, "line ranges: ", range_a, range_o, range_b)
    object_store.add_object(merged_text_blob)
    # TODO(jelmer): Report conflicts, if any?
    if this_entry.mode in (base_entry.mode, other_entry.mode):
        mode = other_entry.mode
    else:
        if base_entry.mode != other_entry.mode:
            # TODO(jelmer): Add a mode conflict
            raise NotImplementedError
        mode = this_entry.mode
    return TreeEntry(new_path, mode, merged_text_blob.id)


def merge_tree(object_store, this_tree, other_tree, common_tree,
               rename_detector=None, file_merger=None):
    """Merge two trees.

    Args:
      object_store: object store to retrieve objects from
      this_tree: Tree id of THIS tree
      other_tree: Tree id of OTHER tree
      common_tree: Tree id of COMMON tree
      rename_detector: Rename detector object (see dulwich.diff_tree)
      file_merger: Three-way file merge implementation
    Returns:
      iterator over objects, either TreeEntry (updating an entry)
        or MergeConflict (indicating a conflict)
    """
    changes_this = tree_changes(object_store, common_tree, this_tree)
    changes_this_by_common_path = {
        change.old.path: change for change in changes_this if change.old}
    changes_this_by_this_path = {
        change.new.path: change for change in changes_this if change.new}
    for other_change in tree_changes(object_store, common_tree, other_tree):
        this_change = changes_this_by_common_path.get(other_change.old.path)
        if this_change == other_change:
            continue
        if other_change.type in (CHANGE_ADD, CHANGE_COPY):
            try:
                this_entry = changes_this_by_this_path[other_change.new.path]
            except KeyError:
                yield TreeEntry(other_change.new.path, other_change.new.mode, other_change.new.sha)
            else:
                if this_entry != other_change.new:
                    # TODO(jelmer): Three way merge instead, with empty common
                    # base?
                    yield MergeConflict(
                        this_entry, other_change.new, other_change.old,
                        'Both this and other add new file %s' %
                        other_change.new.path)
        elif other_change.type == CHANGE_DELETE:
            if this_change and this_change.type not in (
                    CHANGE_DELETE, CHANGE_UNCHANGED):
                yield MergeConflict(
                    this_change.new, other_change.new, other_change.old,
                    '%s is deleted in other but modified in this' %
                    other_change.old.path)
            else:
                yield TreeEntry(other_change.old.path,None, None)
        elif other_change.type == CHANGE_RENAME:
            if this_change and this_change.type == CHANGE_RENAME:
                if this_change.new.path != other_change.new.path:
                    # TODO(jelmer): Does this need to be a conflict?
                    yield MergeConflict(
                        this_change.new, other_change.new, other_change.old,
                        '%s was renamed by both sides (%s / %s)'
                        % (other_change.old.path, other_change.new.path,
                           this_change.new.path))
                else:
                    yield _merge_entry(
                        other_change.new.path,
                        object_store, this_change.new, other_change.new,
                        other_change.old, file_merger=file_merger)
            elif this_change and this_change.type == CHANGE_MODIFY:
                yield _merge_entry(
                    other_change.new.path,
                    object_store, this_change.new, other_change.new,
                    other_change.old, file_merger=file_merger)
            elif this_change and this_change.type == CHANGE_DELETE:
                yield MergeConflict(
                    this_change.new, other_change.new, other_change.old,
                    '%s is deleted in this but renamed to %s in other' %
                    (other_change.old.path, other_change.new.path))
            elif this_change:
                raise NotImplementedError(
                    '%r and %r' % (this_change, other_change))
            else:
                yield TreeEntry(other_change.new.path, other_change.new.mode, other_change.new.sha)
        elif other_change.type == CHANGE_MODIFY:
            if this_change and this_change.type == CHANGE_DELETE:
                yield MergeConflict(
                    this_change.new, other_change.new, other_change.old,
                    '%s is deleted in this but modified in other' %
                    other_change.old.path)
            elif this_change and this_change.type in (
                    CHANGE_MODIFY, CHANGE_RENAME):
                yield _merge_entry(this_change.new.path,
                                   object_store,
                                   this_change.new,
                                   other_change.new,
                                   other_change.old,
                                   file_merger=file_merger)
            elif this_change:
                raise NotImplementedError(
                    '%r and %r' % (this_change, other_change))
            else:
                yield TreeEntry(other_change.new.path, other_change.new.mode, other_change.new.sha)
        else:
            raise NotImplementedError(
                'unsupported change type: %r' % other_change.type)


class MergeResults(object):

    def __init__(self, conflicts):
        self.conflicts = conflicts


def merge(repo, commit_ids, rename_detector=None, file_merger=None):
    """Perform a merge.
    Args:
      repo: Repository object
      commit_ids: list of commit ids (shas with first entry being this and the remaining being other)
      rename_detector: routine to detect files that have been renamed
      file_merger: routine to perform the actual merging of files
    Returns:
       conflicts: list of MergeConflict objects or empty list if none

    Note: File level chunk merge conflicts do NOT (yet?) create MergeConflict objects.
          MergeConflict objects represent tree level conditions that can not be 
          quickly or easily fixed that prevent a merge from completing.

          Instead diff3-style conflict markup within the file is added to make hand 
          editing to fix the conflicts possible before commit.

    FixMe: How should we return the list of chunk level conflicts that need to be hand edited
           to the caller.  Right now they are just printed by _merge_entry.

           A MergeConflict object can NOT be used for that as multiple chunk conflicts are 
           possible in a single file merger, and the resulting file (with diff3 file merge markup)
           should be returned as a TreeEntry.

           Perhaps merge_tree should return a tuple (Tree Entry, List of Conflicts) and throw
           MergeConflict objects to immediately terminate since there really is now way 
           forward when those are detected unless we pass in something that tells it which 
           side to be biased towards (this vs the others aka alice vs bob)
         
    """
    conflicts = []
    lcas = find_merge_base(repo, commit_ids)
    if lcas:
        merge_base = lcas[0]
    # what if no merge base exists?
    #   should we set merge_base to this or other or ...
    [this_commit, other_commit] = commit_ids
    for entry in merge_tree(
            repo.object_store,
            repo.object_store[this_commit].tree,
            repo.object_store[other_commit].tree,
            repo.object_store[merge_base].tree,
            rename_detector=rename_detector,
            file_merger=file_merger):

        if isinstance(entry, MergeConflict):
            conflicts.append(entry)
        else:
            # write results of merge to the working dir only
            print(entry)
            (path, mode, sha) = entry
            full_path = os.path.join(os.fsencode(repo.path), path )
            ensure_dir_exists(os.path.dirname(full_path))
            blob = repo.object_store[sha]
            build_file_from_blob(blob, mode, full_path)

    return conflicts
