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
    os.chdir("merge-recursive")
    print(branch_list("."))
    mb = porcelain_addl.merge_base(".", ["branchC-1", "branchC-2"], all=True)
    print("merge base: ", mb)
    # print(porcelain_addl.merge_base_is_ancestor(".", mb, "master"))
    # print(porcelain_addl.merge_base_is_ancestor(".", mb, "embed-pdf"))
    # mrg_results = porcelain_addl.branch_merge(".", ["master", "embed-pdf"], do_file_merge_ndiff, strategy="ort-ours")
    # mrg_results = porcelain_addl.branch_merge(".", ["master", "embed-pdf"], do_file_merge_myers, strategy="ort-theirs")
    mrg_results = porcelain_addl.branch_merge(".", ["branchC-1", "branchC-2"], do_file_merge_histogram, strategy="ort")
    if mrg_results.merge_complete():
        print("Merge Complete")
    else:
        print("Fatal Conflicts Detected")
        print(mrg_results.fatal_conflicts[0])
    if mrg_results.has_chunk_conflicts():
        for conflict in mrg_results.chunk_conflict_iterator():
            apath = conflict.this_entry.path
            message = conflict.message
            print(apath, message)
    for entry in mrg_results.updated_tree_entry_iterator():
        print(entry)
    porcelain_addl.print_repo_status(".")
    files = ls_files(".")
    print(files)
    
    
if __name__ == '__main__':
    sys.exit(main())
