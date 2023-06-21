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
    branch_list,
    ls_files
)

from dulwich.porcelain import status as porcelain_status

import porcelain_addl

from diff3merge import ( # noqa F401
    do_file_merge_myers,
    do_file_merge_ndiff,
    do_file_merge_histogram
)

from merge_addl import (
    TreeEntry,
    MergeResults,
    MergeConflict
)


def main():
    argv = sys.argv
    if len(argv) != 4:
        return
    blist = []
    blist.append(argv[1])
    blist.append(argv[2])
    strategy = argv[3]
    os.chdir("merge-recursive")
    # print(branch_list("."))
    # mb = porcelain_addl.merge_base(".", blist, all=True)
    # print("merge base: ", mb)
    mrg_results = porcelain_addl.branch_merge(".", blist, do_file_merge_histogram, strategy=strategy)
    if mrg_results.merge_complete():
        print("Merge Complete")
    else:
        print("Structure Conflicts Detected")
        print(mrg_results.structure_conflicts[0])

    # FIXME:  dulwich Index class has no git_conflict_add and git conflict_remove functionality
    # so it never uses STAGEMASK to create multiple staged entries for a merge conflict
    if mrg_results.has_chunk_conflicts():
        for conflict in mrg_results.chunk_conflict_iterator():
            print("3way merge conflict: ", conflict.message)
            print("3way base  : ", conflict.base_entry.sha, conflict.base_entry.path)
            print("3way alice : ", conflict.this_entry.sha, conflict.this_entry.path)
            print("3way bob   : ", conflict.other_entry.sha, conflict.other_entry.path)

    for entry in mrg_results.updated_tree_entry_iterator():
        print(entry)
    porcelain_addl.print_repo_status(".")
    porcelain_addl.ls_files_index(".")
    
if __name__ == '__main__':
    sys.exit(main())
