echo "Test: One Base Commit"
./runit.sh branchA-1 branchA-2 ort
echo " \n----\n\n"

echo "Test: One Base Commit, NonRecursive"
./runit.sh branchA-1 branchA-2 resolve
echo " \n----\n\n"

echo "Test: Two Base Commits"
./runit.sh branchB-1 branchB-2 ort
echo " \n----\n\n"

echo "Test: Two Base Commits, NonRecursive"
./runit.sh branchB-1 branchB-2 resolve
echo " \n----\n\n"

echo "Test: Two Levels of Multiple Bases"
./runit.sh branchC-1 branchC-2 ort
echo " \n----\n\n"

echo "Test: Two Levels of Multiple Bases, NonRecursive"
./runit.sh branchC-1 branchC-2 resolve
echo " \n----\n\n"

echo "Test: Three Levels of Multiple Bases"
./runit.sh branchD-2 branchD-1 ort
echo " \n----\n\n"

echo "Test: Three Levels of Multiple Bases, NonRecursive"
./runit.sh branchD-2 branchD-1 resolve
echo " \n----\n\n"

echo "Test: Three Base Commits"
./runit.sh branchE-1 branchE-2 ort
echo " \n----\n\n"

echo "Test: Three Base Commits, NonRecursive"
./runit.sh branchE-1 branchE-2 resolve
echo " \n----\n\n"

echo "Test: Recursive Conflict" output.txt
./runit.sh branchF-1 branchF-2 ort
echo " \n----\n\n"

echo "Test: Oh So Many Levels"
./runit.sh branchG-1 branchG-2 ort
echo " \n----\n\n"

echo "Test: Conflicting Merge Base"
./runit.sh branchH-1 branchH-2 ort
echo " \n----\n\n"

echo "Test: Conflicting Merge Base with Diff3"
./runit.sh  branchH-2 branchH-1 ort
echo " \n----\n\n"

echo "Test: Conflicting Merge Base Since Resolved"
./runit.sh branchI-1 branchI-2 ort
echo " \n----\n\n"

# skip this test as recursion limit is not supported
# echo "Test: Recursion Limit"
# runit.sh branchC-1 branchC-2 ort

echo "Test: Merge Base for Virtual Commit"
./runit.sh branchJ-1 branchJ-2 ort
echo " \n----\n\n"

echo "Test: Merge Base for Virtual Commit 2"
./runit.sh branchK-1 branchK-2 ort
