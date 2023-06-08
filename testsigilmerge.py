#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim:ts=4:sw=4:softtabstop=4:smarttab:expandtab

import sys
import os
import inspect

import dulwich

from dulwich.repo import Repo

from dulwich.porcelain import (
    open_repo_closing,
    branch_list
)

from dulwich.porcelain import status as porcelain_status

import porcelain_addl

from diff3merge import ( # noqa F401
    do_file_merge_myers,
    do_file_merge_ndiff
)

from merge_addl import (
    TreeEntry,
    MergeResults,
    MergeConflict
)

def working_dir_is_clean(status_tuple):
    (staged, unstaged, untracked) = status_tuple
    is_clean = len(staged["add"]) == 0
    is_clean = is_clean and len(staged["delete"]) == 0
    is_clean = is_clean and len(staged["modify"]) == 0
    is_clean = is_clean and len(unstaged) == 0
    is_clean = is_clean and len(untracked) == 0
    return is_clean

def main():
    os.chdir("Sigil")
    status_info = porcelain_status(".")
    if not working_dir_is_clean(status_info):
        print("Repo must be clean for branch merge to happen")
        return -1
    print(branch_list("."))
    mb = porcelain_addl.merge_base(".", ["master", "embed-pdf"])
    print("merge base: ", mb)
    # print(porcelain_addl.merge_base_is_ancestor(".", mb, "master"))
    # print(porcelain_addl.merge_base_is_ancestor(".", mb, "embed-pdf"))
    with open_repo_closing(".") as r:
        mrg_results = porcelain_addl.branch_merge(r, ["master", "embed-pdf"], do_file_merge_ndiff, update_working_dir=True)
        if mrg_results.merge_complete():
            print("Merge Complete")
        else:
            print("Fatal Conflicts Detected")
            print(mrg_results.self.fatal_conflicts[0])
        if mrg_results.has_chunk_conflicts():
            for (apath, range_o, range_a, range_b) in mrg_results.chunk_conflict_iterator():
                print("Chunk Conflict: ", apath, " line ranges (ancestor, this, other): ", range_o, range_a, range_b)
        for entry in mrg_results.updated_tree_entry_iterator():
            print(entry)

if __name__ == '__main__':
    sys.exit(main())
