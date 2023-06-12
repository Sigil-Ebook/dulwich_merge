# merge.py -- Merge support in Dulwich
# Copyright (C) 2020 Jelmer Vernooij <jelmer@jelmer.uk>
# Copyright (C) 2023 Kevin B. Hendricks, Stratford Ontario Canada
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
import sys
import os
import stat
import posixpath

from collections import namedtuple

from dulwich.index import build_file_from_blob, pathsplit, pathjoin

from dulwich.file import ensure_dir_exists

from dulwich.repo import Repo

from dulwich.objects import TreeEntry, Tree, Blob

from dulwich.patch import is_binary

from dulwich.diff_tree import (
    tree_changes,
    CHANGE_ADD,
    CHANGE_COPY,
    CHANGE_DELETE,
    CHANGE_MODIFY,
    CHANGE_RENAME,
    CHANGE_UNCHANGED,
    )

from graph_fixed import find_merge_base


MergeConflict = namedtuple('Conflict', ['this_entry', 'other_entry', 'base_entry', 'message'])


class MergeConflictEx(Exception):
    def __init__(self, this_entry, other_entry, base_entry, message):
        super().__init__(message)
        self.conflict = MergeConflict(this_entry, other_entry, base_entry, message) 
    """A merge conflict."""


class NotImplementedEx(Exception):
    def __init__(self, message):
        super().__init__(message)


# walk a a tree of trees
def tree_entry_iterator(store, treeid, base=None):
    for (name, mode, sha) in store[treeid].iteritems():
        if base:
            name = posixpath.join(base, name)
        yield TreeEntry(name, mode, sha)
        if stat.S_ISDIR(mode):
            yield from tree_entry_iterator(store, sha, name)


def create_and_store_merged_tree(object_store, merged_tree):
    """create a new merged tree, store it in object_store and return is id

    FIXME: taken almost unchanged from index.py commit_tree which for some unknown reason uses
           a different entry order (path, sha, mode) than the TreeEntries (path, mode, sha) we use
    Args:
      object_store: Object store to add trees to
      merged_tree: list of TreeEntries (path, mode, sha)
    Returns:
      SHA1 of the new tree.
    """
    trees: Dict[bytes, Any] = {b"": {}}

    def add_tree(path):
        if path in trees:
            return trees[path]
        dirname, basename = pathsplit(path)
        t = add_tree(dirname)
        assert isinstance(basename, bytes)
        newtree = {}
        t[basename] = newtree
        trees[path] = newtree
        return newtree

    def build_tree(path):
        tree = Tree()
        for basename, entry in trees[path].items():
            if isinstance(entry, dict):
                mode = stat.S_IFDIR
                sha = build_tree(pathjoin(path, basename))
            else:
                (mode, sha) = entry
            tree.add(basename, mode, sha)
        object_store.add_object(tree)
        return tree.id

    for path, mode, sha in merged_tree:
        tree_path, basename = pathsplit(path)
        tree = add_tree(tree_path)
        tree[basename] = (mode, sha)

    return build_tree(b"")


def _merge_entry(new_path, object_store, this_entry,
                 other_entry, base_entry, file_merger, strategy):
    """ 3 way merge an entry
        Args:
           new_path:      repo relative file path
           object_store:  object store object
           this_entry:    this TreeEntry for file
           other_entry:   other TreeEntry for file
           base_entry:    TreeEntry for common ancestor
           file_merger:   routine to handle the3 actual file merge
           strategy:      merge strategy (supports "ort", "ort-ours", "ort-theirs")
                          see https://git-scm.com/docs/merge-strategies
        Returns:
           TreeEntry for merged file, List of Chunk Level Conflicts
        Raises:
           MergeConflictEx: to indicate fatal conflict preventing merge
           NotImplementedEx
    """
       
    chunk_conflicts = []
    if file_merger is None:
        raise MergeConflictEx(
            this_entry, other_entry,
            other_entry.old,
            'Conflict in %s but no file merger provided'
            % new_path)
    this_content = object_store[this_entry.sha].as_raw_string()
    other_content =  object_store[other_entry.sha].as_raw_string()
    base_content = object_store[base_entry.sha].as_raw_string()
    # handle when binary files detected
    if is_binary(this_content) or is_binary(other_content) or is_binary(base_content):
        if (this_content != other_content):
            if strategy == "ort-ours":
                return TreeEntry(this_entry.path, this_entry.mode, this_entry.sha), chunk_conflicts
            elif strategy == "ort-theirs":
                return TreeEntry(other_entry.path, other_entry.mode, other_entry.sha), chunk_conflicts
            else:
                raise MergeConflictEx(this_entry, other_entry, base_entry,'3 way diff and merge of binary files not supported %s' % this_entry.path) 
        else:
            return TreeEntry(this_entry.path, this_entry.mode, this_entry.sha), chunk_conflicts

    # use diff3merge to handle the actual merging
    (merged_text, conflict_list) = file_merger(this_content, other_content, base_content, strategy)
    
    for (range_o, range_a, range_b) in conflict_list:
        chunk_conflicts.append((new_path, range_o, range_a, range_b))

    merged_text_blob = Blob.from_string(merged_text)
    object_store.add_object(merged_text_blob)
    if this_entry.mode in (base_entry.mode, other_entry.mode):
        mode = other_entry.mode
    else:
        if base_entry.mode != other_entry.mode:
            raise NotImplementedEx('tree entry mode changes are not supported')
        mode = this_entry.mode
    return TreeEntry(new_path, mode, merged_text_blob.id), chunk_conflicts


def merge_tree(object_store, this_tree, other_tree, common_tree,
               rename_detector=None, file_merger=None, strategy="ort"):
    """Merge two trees.

    Args:
      object_store:    object store to retrieve objects from
      this_tree:       tree id of THIS tree (aka alice)
      other_tree:      tree id of OTHER tree (aka bob)
      common_tree:     tree id of COMMON tree (aka ancestor or orignal)
      rename_detector: Rename detector object (see dulwich.diff_tree)
      file_merger:     3-way file merge implementation
      strategy:        file merge strategy (supports "ort", "ort-ours", "ort-theirs")
                          see https://git-scm.com/docs/merge-strategies
    Returns:
      iterator over changed objects: tuple of TreeEntry, chunk conflict list)
    Raises:
      MergeConflictEx (indicating a conflict preventing a merge)
      NotImplementedEx
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
                yield TreeEntry(other_change.new.path, other_change.new.mode, other_change.new.sha), []
            else:
                if this_entry != other_change.new:
                    # TODO(jelmer): Three way merge instead, with empty common
                    # base?
                    raise MergeConflictEx(
                        this_entry, other_change.new, other_change.old,
                        'Both this and other add new file %s' %
                        other_change.new.path)
        elif other_change.type == CHANGE_DELETE:
            if this_change and this_change.type not in (
                    CHANGE_DELETE, CHANGE_UNCHANGED):
                raise MergeConflictEx(
                    this_change.new, other_change.new, other_change.old,
                    '%s is deleted in other but modified in this' %
                    other_change.old.path)
            else:
                yield TreeEntry(other_change.old.path,None, None), []
        elif other_change.type == CHANGE_RENAME:
            if this_change and this_change.type == CHANGE_RENAME:
                if this_change.new.path != other_change.new.path:
                    # TODO(jelmer): Does this need to be a conflict?
                    raise MergeConflictEx(
                        this_change.new, other_change.new, other_change.old,
                        '%s was renamed by both sides (%s / %s)'
                        % (other_change.old.path, other_change.new.path,
                           this_change.new.path))
                else:
                    yield _merge_entry(
                        other_change.new.path,
                        object_store, this_change.new, other_change.new,
                        other_change.old, file_merger=file_merger, strategy=strategy)
            elif this_change and this_change.type == CHANGE_MODIFY:
                yield _merge_entry(
                    other_change.new.path,
                    object_store, this_change.new, other_change.new,
                    other_change.old, file_merger=file_merger, strategy=strategy)
            elif this_change and this_change.type == CHANGE_DELETE:
                raise MergeConflictEx(
                    this_change.new, other_change.new, other_change.old,
                    '%s is deleted in this but renamed to %s in other' %
                    (other_change.old.path, other_change.new.path))
            elif this_change:
                raise NotImplementedEx('%r and %r' % (this_change, other_change))
            else:
                yield TreeEntry(other_change.new.path, other_change.new.mode, other_change.new.sha), []
        elif other_change.type == CHANGE_MODIFY:
            if this_change and this_change.type == CHANGE_DELETE:
                raise MergeConflictEx(
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
                                   file_merger=file_merger,
                                   strategy=strategy)
            elif this_change:
                raise NotImplementedEx(
                    '%r and %r' % (this_change, other_change))
            else:
                yield TreeEntry(other_change.new.path, other_change.new.mode, other_change.new.sha), []
        else:
            raise NotImplementedEx(
                'unsupported change type: %r' % other_change.type)


class MergeResults(object):

    def __init__(self):
        self.fatal_conflicts = []
        self.chunk_conflicts = []
        self.hand_merge_set = set()
        self.updated_tree_entries = []
        self.tree_id = None

    def add_entry(self, entry):
        self.updated_tree_entries.append(entry)

    def add_chunk_conflict(self, conflict):
        self.chunk_conflicts.append(conflict)
        (name, range_0, range_a, range_b) = conflict
        self.hand_merge_set.add(name)

    def add_fatal_conflict(self, fatal):
        self.fatal_conflicts.append(fatal)

    def merge_complete(self):
        return len(self.fatal_conflicts) == 0

    def has_chunk_conflicts(self):
        return self.merge_complete() and len(self.chunk_conflicts) > 0

    def updated_tree_entry_iterator(self):
        for entry in self.updated_tree_entries:
            yield entry
            
    def needs_to_be_hand_merged(self, name):
        return name in self.hand_merge_set

    def chunk_conflict_iterator(self):
        for conflict in self.chunk_conflicts:
            yield conflict



def merge(repo, commit_ids, rename_detector=None, file_merger=None, strategy="ort"):
    """Perform a merge.
    Args:
      repo:            repository object
      commit_ids:      list of commit ids (shas with first entry being this and the remaining being other)
      rename_detector: routine to detect files that have been renamed
      file_merger:     routine to perform the actual merging of files
      strategy:        merge strategy (supports "ort", "ort-ours", "ort-theirs")
                          see https://git-scm.com/docs/merge-strategies
    Returns:
      MergeResults object
    """
    mrg_results = MergeResults()
    lcas = find_merge_base(repo, commit_ids)
    
    # FIXME: technically if multiple lcas are found we should be
    # merging each lcas to find the proper "recursive" merge base
    
    if lcas:
        merge_base = lcas[0]

    # FIXME: We should abort if no merge base exists at it is
    # required for a 3-way merge

    [this_commit, other_commit] = commit_ids

    this_tree_id = repo.object_store[this_commit].tree
    other_tree_id = repo.object_store[other_commit].tree
    base_tree_id = repo.object_store[merge_base].tree

    # to prevent corruption walk all changed entries first
    # before trying to build the merged tree
    try: 
        for entry, chunk_conflicts in merge_tree(
                repo.object_store,
                this_tree_id,
                other_tree_id,
                base_tree_id,
                rename_detector=rename_detector,
                file_merger=file_merger,
                strategy=strategy):

            # store MergeResults
            mrg_results.add_entry(entry)
            for (apath, range_o, range_a, range_b ) in chunk_conflicts:
                mrg_results.add_chunk_conflict((apath, range_o, range_a, range_b))
              
    except MergeConflictEx as exc:
        print(exc.message)
        mrg_results.add_fatal_conflict(exc.conflict)
        return mrg_results
    
    except NotImplementedEx as exc:
        print(exc.message)
        mrg_results.add_fatal_conflict(exc)
        return mrg_results

    # if reached here there were no fatal conflicts

    # create a sort list of merged tree entries and store it
    merged_tree = {}
    for (path, mode, sha) in tree_entry_iterator(repo.object_store, this_tree_id):
        merged_tree[path] = (mode, sha)
    for (path, mode, sha) in mrg_results.updated_tree_entry_iterator():
        merged_tree[path] = (mode, sha)
    merged_tree_entries = []
    paths = list(merged_tree.keys())
    paths.sort()
    for apath in paths:
        (mode, sha) = merged_tree[apath]
        merged_tree_entries.append(TreeEntry(path, mode, sha))

    mrg_results.tree_id = create_and_store_merged_tree(repo.object_store, merged_tree_entries)

    # FIXME: The remainder of this should probably be made controllable by options passed in to merge
    #        But given the number of merge options (myers, histogram, ndiff)
    #        and the possible stratgies: ort, ort-ours, ort-theirs, perhaps a namedtuple called
    #        MergeOptions should be created and passed in and perhaps include the following:
    #           do_update_working_dir T/F
    #           do_stage T/F 
    #           do_commit: T/F which implies both do_update_working_dir and do_stage both true 

    # FIXME: Or instead of a MergeOptions approach we simplify this
    # routine and return the merged tree id inside MergeResults
    # and let the caller handle all the rest

    # For now lets update the working dir and stage the results
    to_stage_relpaths = []
    for entry in mrg_results.updated_tree_entry_iterator():
        (path, mode, sha) = entry
        full_path = os.path.join(os.fsencode(repo.path), path)
        ensure_dir_exists(os.path.dirname(full_path))
        blob = repo.object_store[sha]
        build_file_from_blob(blob, mode, full_path)
        if not mrg_results.needs_to_be_hand_merged(path):
            to_stage_relpaths.append(path)
    if len(to_stage_relpaths) > 0:
        repo.stage(to_stage_relpaths)

    # FIXME: should we also commit here if no chunk conflicts exist?
    #        or let the caller decide

    return mrg_results
