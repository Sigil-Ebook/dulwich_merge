dulwich_merge
=============

The dulwich_merge project is a working attempt at adding
a true merge capability to the dulwich (the pure python implmentation of git),
while extending the capability of creating diffs between index, working dir,
trees, tags, commits, and branches.

For current dulwich see:
    
    https://github.com/jelmer/dulwich

Anyone interested in welcome to add to this project or build upon it following
the current license of the dulwich project:

    See https://githgub.com/jelmer/dulwich/Copying

    
Testing current merge and extended support
==========================================

The code in dulwich_merge is pure python and it relies on having the
dulwich module installed in your python3

    pip3 install dulwich

Then cd into the dulwich_merge and unarchive a recent snapshot of the
Sigil's githgub repo that can be obtained from this repo's Release page
    
    tar -zxvf Sigil_repo_snapshot.tar.gz

This will create a local copy of the Sigil-Ebooks/Sigil github repo called Sigil

To test the extended diff capabilities run:

   python3 ./testdiff.py


To test the current state of merge support run:

    python3 ./testsigilmerge.py

It will merge two branches from Sigil's repo, in this case "master" and "embed-pdf"
into the local repo's working directory.  No commmits are done but changed files and
any associated conflicts are shown.

All of the changes needed for merge support are housed in separate files in dulwich_merge.
Extensions meant for specific current dulwich source files have an "_addl" added to the file
name.  A fixed version of current dulwich's graph.py is called graph_fixed.py is also included.

The working directory shows the results of the merge.
The output shows a single simple conflict in src/Dialogs/PluginRunner.cpp that when edited
in the working directory of the Sigil repo can be easily fixed before commit.


What We Need From You
=====================

Please test this added merge capability on your own repos! with multiple branches and report
back what is broken and what needs to be implemented yet, your fixes, etc.

Once we have something robust and cleaned up, we will offer these changes to the current dulwich project.

