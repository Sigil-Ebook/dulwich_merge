# index_addl.py -- File parser/writer for the git index file
# Copyright (C) 2023 Kevin B. Hendricks, Stratford Ontario Canada
# Copyright (C) 2008-2013 Jelmer Vernooij <jelmer@jelmer.uk>
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


def changes_from_workingdir(names, lookup_entry, object_store,
                            index, want_unchanged=False):
    """Find the differences between the contents of the index and
    the working directory.
    Args:
      names: Iterable of names in the working copy
      lookup_entry: Function to lookup an entry in the working copy
      object_store: Object store to use for retrieving index contents
      index: Index object of current repo
      want_unchanged: Whether unchanged files should be reported
    Returns: Iterator over tuples with (oldpath, newpath),
        (oldmode, newmode), (oldsha, newsha)
    """
    # TODO(jelmer): Support a include_trees option
    other_names = set(names)

    if index is not None:
        for name, entry in index.iteritems():
            sha = entry.sha
            mode = entry.mode
            try:
                (other_sha, other_mode) = lookup_entry(name)
            except KeyError:
                # Was removed
                yield ((name, None), (mode, None), (sha, None))
            else:
                other_names.remove(name)
                if (want_unchanged or other_sha != sha or other_mode != mode):
                    yield ((name, name), (mode, other_mode), (sha, other_sha))

    # Mention untracked files
    for name in other_names:
        try:
            (other_sha, other_mode) = lookup_entry(name)
        except KeyError:
            pass
        else:
            yield ((None, name), (None, other_mode), (None, other_sha))
