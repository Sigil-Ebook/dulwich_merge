#!/usr/bin/env python
# -*- coding: utf-8 -*-
# vim:ts=4:sw=4:softtabstop=4:smarttab:expandtab

import sys
import os
import inspect

from dulwich import porcelain
import porcelain_addl

def main():
    os.chdir("Sigil")
    print(porcelain.branch_list("."))

    print("Testing diff of tree against tree")
    porcelain_addl.diff(".", committish1=b"master", committish2=b"embed-pdf")

    print("\nTesting diff of tree against working dir")
    porcelain_addl.diff(".", committish1=b"HEAD")

    print("\nTesting diff of tree against index")
    porcelain_addl.diff(".", committish1=b"HEAD", cached=True)

    print("\nTesting diff of index against working dir")
    porcelain_addl.diff(".")


if __name__ == '__main__':
    sys.exit(main())
