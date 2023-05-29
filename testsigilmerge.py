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

import porcelain_addl

from diff3merge import ( # noqa F401
    do_file_merge_myers,
    do_file_merge_ndiff)


def main():
    os.chdir("Sigil")
    print(branch_list("."))
    mb = porcelain_addl.merge_base(".", ["master", "embed-pdf"])
    print(mb)
    print(porcelain_addl.merge_base_is_ancestor(".", mb, "master"))
    print(porcelain_addl.merge_base_is_ancestor(".", mb, "embed-pdf"))
    with open_repo_closing(".") as r:
        conflicts = porcelain_addl.branch_merge(r, ["master", "embed-pdf"], do_file_merge_ndiff)
        print(conflicts)

if __name__ == '__main__':
    sys.exit(main())
