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

_DULWICH_TEST = b"DulwichRecursiveMerge <dulwich@dulwich.com>"

MergeConflict = namedtuple('MergeConflict', ['conflict_type', 'this_entry', 'other_entry', 'base_entry', 'message'])
#      conflict types are: 'fatal', 'chunk', 'ni'


MergeOptions = namedtuple('MergeOptions', ['file_merger', 'rename_detector', 'strategy'])
#      supported merge strategies are:  'ort', 'ort-ours', 'ort-theirs'
#      see https://git-scm.com/docs/merge-strategies


NO_ENTRY = TreeEntry(None, None, None)

# walk a tree of trees
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


def _updated_tree_entries_with_changes(repo, this_tree_id, mrg_results):
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
    return merged_tree_entries    


def _create_virtual_tree_commit(repo, tree_id, parent1, parent2):
    print('virtual commit of parents', parent1, parent2)
    message = b'virtual commit of parents ' +  parent1 + b' ' +  parent2
    merge_parents = [parent1, parent2]
    vcommit = repo.do_commit(
        message=message,
        committer=_DULWICH_TEST,
        author=_DULWICH_TEST,
        commit_timestamp=None,
        commit_timezone=None,
        author_timestamp=None,
        author_timezone=None,
        tree=tree_id,
        encoding=b'utf-8',
        ref=None,
        merge_heads=merge_parents,
        no_verify=False,
        sign=False
    )
    print("vcommit: ", vcommit)
    return vcommit


def _create_virtual_merge_base(repo, moptions, b1, b2, lcas_commits, result):
    if len(lcas_commits) == 0:
        lcas_commits = find_merge_base(repo, [b1, b2])
        lcas_commits.reverse()
    base = lcas_commits.pop(0)
    if not base:
         # FIXME: we should use an empty tree as the merge base for b1 and b2
         # since no common ancestor exists according to the git logic
         return -1
    print('cvmb: ', base)
    for cmt in lcas_commits:
        nresult = []
        rv = _create_virtual_merge_base(repo, moptions, base, cmt, [], nresult)
        if rv < 0:
            return -1
        base = nresult[0]
    if not base:
        return -1
    # now do the merge b1 and b2 using base
    b1_tree_id = repo.object_store[b1].tree
    b2_tree_id = repo.object_store[b2].tree
    base_tree_id = repo.object_store[base].tree
    mrg_results = MergeResults()
    for entry, conflicts in merge_tree(repo.object_store, moptions, b1_tree_id, b2_tree_id, base_tree_id):
            for conflict in conflicts:
                # explicitly allow chunk conflicts to pass through
                if conflict.conflict_type == 'fatal' or conflict.conflict_type == 'ni':
                    return -1
            if entry.path and entry.mode and entry.sha:
                mrg_results.add_entry(entry)
        
    # create the new merged tree from merged entries and store it
    merged_tree_entries = _updated_tree_entries_with_changes(repo, b1_tree_id, mrg_results)
    tree_id = create_and_store_merged_tree(repo.object_store, merged_tree_entries)

    # create a virtual commit that does not update head whose parents are this_commit and other_commit
    virtual_tree_commit = _create_virtual_tree_commit(repo, tree_id, b1, b2)
    result.append(virtual_tree_commit)
    return 0


def _merge_entry(moptions, new_path, object_store, this_entry,
                 other_entry, base_entry):
    """ 3 way merge an entry
        Args:
           moptions:      MergeOptions object
           new_path:      repo relative file path
           object_store:  object store object
           this_entry:    this TreeEntry for file
           other_entry:   other TreeEntry for file
           base_entry:    TreeEntry for common ancestor
        Returns:
           TreeEntry for merged file, List of MergeConflicts
    """
       
    if moptions.file_merger is None:
        conflict = MergeConflict('fatal', this_entry, other_entry, other_entry.old,
                                 'Conflict in %s but no file merger provided' % new_path)
        return NO_ENTRY, [conflict]
    
    this_content = object_store[this_entry.sha].as_raw_string()
    other_content =  object_store[other_entry.sha].as_raw_string()
    base_content = object_store[base_entry.sha].as_raw_string()
    
    # handle when binary files detected
    if is_binary(this_content) or is_binary(other_content) or is_binary(base_content):
        if (this_content != other_content):
            if moptions.strategy == "ort-ours":
                return TreeEntry(this_entry.path, this_entry.mode, this_entry.sha), []
            elif moptions.strategy == "ort-theirs":
                return TreeEntry(other_entry.path, other_entry.mode, other_entry.sha), []
            else:
                conflict = MergeConflict('fatal',this_entry, other_entry, base_entry,
                                         '3 way diff and merge of binary files not supported %s' % this_entry.path) 
                return NO_ENTRY, [conflict]  
        else:
            return TreeEntry(this_entry.path, this_entry.mode, this_entry.sha), []

    # for text use diff3merge to handle the actual merging
    (merged_text, conflict_list) = moptions.file_merger(this_content, other_content, base_content, moptions.strategy)
    chunk_conflicts = []
    for (range_o, range_a, range_b) in conflict_list:
        message=str(new_path) + ' in line ranges ' + str(range_o) + str(range_a) + str(range_b)
        conflict = MergeConflict('chunk', this_entry, other_entry, base_entry, message)
        chunk_conflicts.append(conflict)

    merged_text_blob = Blob.from_string(merged_text)
    object_store.add_object(merged_text_blob)
    if this_entry.mode in (base_entry.mode, other_entry.mode):
        mode = other_entry.mode
    else:
        if base_entry.mode != other_entry.mode:
            message = 'tree entry mode changes are not supported'
            conflict = MergeConflict('ni', this_entry, other_entry, base_entry, message)
            return NO_ENTRY, [conflict]
        mode = this_entry.mode
    return (TreeEntry(new_path, mode, merged_text_blob.id), chunk_conflicts)


def merge_tree(object_store, moptions, this_tree, other_tree, common_tree):
    """Merge two trees.

    Args:
      object_store:    object store to retrieve objects from
      moptions:        MergeOptions object
      this_tree:       tree id of THIS tree (aka alice)
      other_tree:      tree id of OTHER tree (aka bob)
      common_tree:     tree id of COMMON tree (aka ancestor or orignal)
    Returns:
      iterator over changed objects: tuple of TreeEntry, List of MergeConflicts)
    """
    changes_this = tree_changes(object_store, common_tree, this_tree)
    changes_this_by_common_path = { change.old.path: change for change in changes_this if change.old }
    changes_this_by_this_path = { change.new.path: change for change in changes_this if change.new }
    
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
                    # TODO(jelmer): Three way merge instead, with empty common base?
                    conflict = MergeConflict('fatal', this_entry, other_change.new, other_change.old,
                                             'Both this and other add new file %s' % other_change.new.path)
                    yield NO_ENTRY, [conflict]

        elif other_change.type == CHANGE_DELETE:
            if this_change and this_change.type not in (CHANGE_DELETE, CHANGE_UNCHANGED):
                conflict = MergeConflict('fatal', this_change.new, other_change.new, other_change.old,
                                         '%s is deleted in other but modified in this' % other_change.old.path)
                yield NO_ENTRY, [conflict]
                
            else:
                yield TreeEntry(other_change.old.path, None, None), []
                
        elif other_change.type == CHANGE_RENAME:
            if this_change and this_change.type == CHANGE_RENAME:
                if this_change.new.path != other_change.new.path:
                    # TODO(jelmer): Does this need to be a conflict?
                    conflict = MergeConflict('fatal', this_change.new, other_change.new, other_change.old,
                                             '%s was renamed by both sides (%s / %s)' %
                                             (other_change.old.path, other_change.new.path, this_change.new.path))
                    yield NO_ENTRY, [conflict]
                else:
                    yield _merge_entry(moptions, other_change.new.path, object_store, this_change.new,
                                       other_change.new, other_change.old)
            elif this_change and this_change.type == CHANGE_MODIFY:
                yield _merge_entry(moptions, other_change.new.path, object_store, this_change.new,
                                   other_change.new, other_change.old)
            elif this_change and this_change.type == CHANGE_DELETE:
                conflict = MergeConflict('fatal', this_change.new, other_change.new, other_change.old,
                                         '%s is deleted in this but renamed to %s in other' %
                                         (other_change.old.path, other_change.new.path))
                yield NO_ENTRY, [conflict]
            elif this_change:
                message = 'Not Implemented %r and %r' % (this_change, other_change)
                conflict = MergeConflict('ni',this_entry, other_entry, base_entry, message)
                yield NO_ENTRY, [conflict]
            else:
                yield TreeEntry(other_change.new.path, other_change.new.mode, other_change.new.sha), []

        elif other_change.type == CHANGE_MODIFY:
            if this_change and this_change.type == CHANGE_DELETE:
                conflict = MergeConflict('fatal', this_change.new, other_change.new, other_change.old,
                                         '%s is deleted in this but modified in other' % other_change.old.path)
                yield NO_ENTRY, [conflict]
            elif this_change and this_change.type in (CHANGE_MODIFY, CHANGE_RENAME):
                yield _merge_entry(moptions, this_change.new.path, object_store, this_change.new,
                                   other_change.new, other_change.old)
            elif this_change:
                message = 'Not Implemented %r and %r' % (this_change, other_change)
                conflict = MergeConflict('ni',this_entry, other_entry, base_entry, message)
                yield NO_ENTRY, [conflict]
            else:
                yield TreeEntry(other_change.new.path, other_change.new.mode, other_change.new.sha), []
        else:
            message = 'Not Implemented %r' % other_change.type
            conflict = MergeConflict('ni',this_entry, other_entry, base_entry, message)
            yield NO_ENTRY, [conflict]


class MergeResults(object):

    def __init__(self):
        self.fatal_conflicts = []
        self.chunk_conflicts = []
        self.hand_merge_set = set()
        self.updated_tree_entries = []
        self.tree_id = None

    def add_fatal_conflict(self, fatal):
        self.fatal_conflicts.append(fatal)

    def add_chunk_conflict(self, conflict):
        self.chunk_conflicts.append(conflict)
        (type, this_entry, other_entry, base_entry, message) = conflict
        self.hand_merge_set.add(this_entry.path)

    def chunk_conflict_iterator(self):
        for conflict in self.chunk_conflicts:
            yield conflict

    def add_entry(self, entry):
        self.updated_tree_entries.append(entry)

    def updated_tree_entry_iterator(self):
        for entry in self.updated_tree_entries:
            yield entry

    def has_fatal_conflicts(self):
        return len(self.fatal_conflicts) > 0
    
    def has_chunk_conflicts(self):
        return len(self.chunk_conflicts) > 0

    def merge_complete(self):
        return len(self.fatal_conflicts) == 0
            
    def needs_to_be_hand_merged(self, apath):
        return apath in self.hand_merge_set



def merge(repo, moptions, commit_ids):
    """Perform a merge.
    Args:
      repo:            repository object
      moptions:        MergeOptions object
      commit_ids:      list of commit ids (shas with first entry being this and the remaining being other)
    Returns:
      MergeResults object
    """
    mrg_results = MergeResults()

    if len(commit_ids) != 2:
        mrg_results.fatal_conflicts.append(MergeConflict('fatal',None, None, None, "can only merge two commits"))
        return mrg_results
        
    [this_commit, other_commit] = commit_ids
    # for some reason git swaps the order of the branch commits used to find the lcas
    # when a non-recursive merge strategy is chosen.
    # I can see no reason for this but we need to do the same to pass their test suite
    branch_list = []
    # if moptions.strategy in ['ort', 'ort-ours', 'ort-theirs', 'recursive']:
    branch_list.append(this_commit)
    branch_list.append(other_commit)
    # else:
    #     branch_list.append(other_commit)
    #     branch_list.append(this_commit)
    lcas = find_merge_base(repo, branch_list)

    if not lcas or len(lcas) == 0:
        # FIXME: no merge base found abort for now
        # git uses empty tree as merge base when this happens 
        mrg_results.fatal_conflicts.append(MergeConflict('fatal',None, None, None, "No merge base found"))
        return mrg_results

    print(len(lcas), " merge bases found")
    
    merge_base = lcas[-1]

    # if multiple lcas found we need to recursively merge all merge bases to create
    # a virtual merge base to continue
    # if merge of lcas has fatal conflicts default to using the first merge base
    # skip if using non-recursive strategy such as resolve
    if len(lcas) > 1 and moptions.strategy in ['ort', 'ort-ours', 'ort-theirs', 'recursive']:
        lcas.reverse()
        b1 = lcas.pop(0)
        b2 = lcas.pop(0)
        result = []
        rv = _create_virtual_merge_base(repo, moptions, b1, b2, lcas, result)
        if rv == 0:
            merge_base = result[0]

    this_tree_id = repo.object_store[this_commit].tree
    other_tree_id = repo.object_store[other_commit].tree
    base_tree_id = repo.object_store[merge_base].tree

    # walk all changed entries first before trying to build the merged tree
    for entry, conflicts in merge_tree(repo.object_store,
                                       moptions,
                                       this_tree_id,
                                       other_tree_id,
                                       base_tree_id):
        for conflict in conflicts:
            if conflict.conflict_type == 'fatal' or conflict.conflict_type == 'ni':
                mrg_resuts.add_fatal_conflict(conflict)
            else:
                mrg_results.add_chunk_conflict(conflict)

        if entry.path and entry.mode and entry.sha:
            mrg_results.add_entry(entry)

    if mrg_results.merge_complete():

        # create the new merged tree from merged entries and store it
        merged_tree_entries = _updated_tree_entries_with_changes(repo, this_tree_id, mrg_results)
        mrg_results.tree_id = create_and_store_merged_tree(repo.object_store, merged_tree_entries)

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

    return mrg_results
