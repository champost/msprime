#
# Copyright (C) 2016-2017 University of Oxford
#
# This file is part of msprime.
#
# msprime is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# msprime is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with msprime.  If not, see <http://www.gnu.org/licenses/>.
#
"""
Test cases for the supported topological variations and operations.
"""
from __future__ import print_function
from __future__ import division

try:
    # We use the zip as iterator functionality here.
    from future_builtins import zip
except ImportError:
    # This fails for Python 3.x, but that's fine.
    pass

import unittest
import itertools
import random
import six

import msprime
import _msprime
import tests


def permute_nodes(ts, node_map):
    """
    Returns a copy of the specified tree sequence such that the nodes are
    permuted according to the specified map.
    """
    # Mapping from nodes in the new tree sequence back to nodes in the original
    reverse_map = [0 for _ in node_map]
    for j in range(ts.num_nodes):
        reverse_map[node_map[j]] = j
    old_nodes = list(ts.nodes())
    new_nodes = msprime.NodeTable()
    for j in range(ts.num_nodes):
        old_node = old_nodes[reverse_map[j]]
        new_nodes.add_row(
            flags=old_node.flags, name=old_node.name,
            population=old_node.population, time=old_node.time)
    new_edgesets = msprime.EdgesetTable()
    for edgeset in ts.edgesets():
        new_edgesets.add_row(
            left=edgeset.left, right=edgeset.right, parent=node_map[edgeset.parent],
            children=tuple(sorted([node_map[c] for c in edgeset.children])))
    new_sites = msprime.SiteTable()
    new_mutations = msprime.MutationTable()
    for site in ts.sites():
        new_sites.add_row(
            position=site.position, ancestral_state=site.ancestral_state)
        for mutation in site.mutations:
            new_mutations.add_row(
                site=site.index, derived_state=mutation.derived_state,
                node=node_map[mutation.node])
    return msprime.load_tables(
        nodes=new_nodes, edgesets=new_edgesets, sites=new_sites,
        mutations=new_mutations)


def insert_redundant_breakpoints(ts):
    """
    Builds a new tree sequence containing redundant breakpoints.
    """
    tables = ts.dump_tables()
    tables.edgesets.reset()
    for r in ts.edgesets():
        x = r.left + (r.right - r.left) / 2
        tables.edgesets.add_row(
            left=r.left, right=x, children=r.children, parent=r.parent)
        tables.edgesets.add_row(
            left=x, right=r.right, children=r.children, parent=r.parent)
    new_ts = msprime.load_tables(**tables._asdict())
    assert new_ts.num_edgesets == 2 * ts.num_edgesets
    return new_ts


def single_childify(ts):
    """
    Builds a new equivalent tree sequence whose edgesets all have singleton children.
    """
    tables = ts.dump_tables()
    tables.edgesets.reset()
    for u in range(ts.num_nodes):
        parent_edges = [r for r in ts.edgesets() if u == r.parent]
        children = []
        for r in parent_edges:
            children.extend(r.children)
        for child in set(children):
            edges = [r for r in parent_edges if child in r.children]
            lefts = [r.left for r in edges]
            rights = [r.right for r in edges]
            do_lefts = [lefts[0]]
            do_rights = []
            for k in range(len(lefts)-1):
                if lefts[k+1] != rights[k]:
                    do_lefts.append(lefts[k+1])
                    do_rights.append(rights[k])
            do_rights.append(rights[-1])
            assert len(do_lefts) == len(do_rights)
            for k in range(len(do_lefts)):
                tables.edgesets.add_row(
                    left=do_lefts[k], right=do_rights[k], children=(child,), parent=u)
    new_ts = msprime.load_tables(**tables._asdict())
    return new_ts


class TopologyTestCase(unittest.TestCase):
    """
    Superclass of test cases containing common utilities.
    """
    random_seed = 123456

    def assert_haplotypes_equal(self, ts1, ts2):
        h1 = list(ts1.haplotypes())
        h2 = list(ts2.haplotypes())
        self.assertEqual(h1, h2)

    def assert_variants_equal(self, ts1, ts2):
        v1 = list(ts1.variants(as_bytes=True))
        v2 = list(ts2.variants(as_bytes=True))
        self.assertEqual(v1, v2)

    def check_num_samples(self, ts, x):
        """
        Compare against x, a list of tuples of the form
        `(tree number, parent, number of samples)`.
        """
        k = 0
        tss = ts.trees(sample_counts=True)
        t = next(tss)
        for j, node, nl in x:
            while k < j:
                t = next(tss)
                k += 1
            self.assertEqual(nl, t.num_samples(node))

    def check_num_tracked_samples(self, ts, tracked_samples, x):
        k = 0
        tss = ts.trees(sample_counts=True, tracked_samples=tracked_samples)
        t = next(tss)
        for j, node, nl in x:
            while k < j:
                t = next(tss)
                k += 1
            self.assertEqual(nl, t.num_tracked_samples(node))

    def check_sample_iterator(self, ts, x):
        """
        Compare against x, a list of tuples of the form
        `(tree number, node, sample ID list)`.
        """
        k = 0
        tss = ts.trees(sample_lists=True)
        t = next(tss)
        for j, node, samples in x:
            while k < j:
                t = next(tss)
                k += 1
            for u, v in zip(samples, t.samples(node)):
                self.assertEqual(u, v)


class TestRecordSquashing(TopologyTestCase):
    """
    Tests that we correctly squash adjacent equal records together.
    """
    def test_single_record(self):
        nodes = six.StringIO("""\
        id  is_sample   time
        0   1           0
        1   1           0
        2   0           1
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0       1       2       0,1
        1       2       2       0,1
        """)
        ts = msprime.load_text(nodes, edgesets)
        tss = ts.simplify()
        self.assertEqual(list(tss.nodes()), list(ts.nodes()))
        simplified_edgesets = list(tss.edgesets())
        self.assertEqual(len(simplified_edgesets), 1)
        e = simplified_edgesets[0]
        self.assertEqual(e.left, 0)
        self.assertEqual(e.right, 2)

    def test_single_tree(self):
        ts = msprime.simulate(10, random_seed=self.random_seed)
        ts_redundant = insert_redundant_breakpoints(ts)
        tss = ts_redundant.simplify()
        self.assertEqual(list(tss.records()), list(ts.records()))

    def test_many_trees(self):
        ts = msprime.simulate(
                20, recombination_rate=5,
                random_seed=self.random_seed)
        self.assertGreater(ts.num_trees, 2)
        ts_redundant = insert_redundant_breakpoints(ts)
        tss = ts_redundant.simplify()
        self.assertEqual(list(tss.records()), list(ts.records()))


class TestRedundantBreakpoints(TopologyTestCase):
    """
    Tests for dealing with redundant breakpoints within the tree sequence.
    These are records that may be squashed together into a single record.
    """
    def test_single_tree(self):
        ts = msprime.simulate(10, random_seed=self.random_seed)
        ts_redundant = insert_redundant_breakpoints(ts)
        self.assertEqual(ts.sample_size, ts_redundant.sample_size)
        self.assertEqual(ts.sequence_length, ts_redundant.sequence_length)
        self.assertEqual(ts_redundant.num_trees, 2)
        trees = [t.parent_dict for t in ts_redundant.trees()]
        self.assertEqual(len(trees), 2)
        self.assertEqual(trees[0], trees[1])
        self.assertEqual([t.parent_dict for t in ts.trees()][0], trees[0])

    def test_many_trees(self):
        ts = msprime.simulate(
                20, recombination_rate=5, random_seed=self.random_seed)
        self.assertGreater(ts.num_trees, 2)
        ts_redundant = insert_redundant_breakpoints(ts)
        self.assertEqual(ts.sample_size, ts_redundant.sample_size)
        self.assertEqual(ts.sequence_length, ts_redundant.sequence_length)
        self.assertGreater(ts_redundant.num_trees, ts.num_trees)
        self.assertGreater(ts_redundant.num_edgesets, ts.num_edgesets)
        redundant_trees = ts_redundant.trees()
        redundant_t = next(redundant_trees)
        comparisons = 0
        for t in ts.trees():
            while redundant_t is not None and redundant_t.interval[1] <= t.interval[1]:
                self.assertEqual(t.parent_dict, redundant_t.parent_dict)
                comparisons += 1
                redundant_t = next(redundant_trees, None)
        self.assertEqual(comparisons, ts_redundant.num_trees)


class TestUnaryNodes(TopologyTestCase):
    """
    Tests for situations in which we have unary nodes in the tree sequence.
    """
    def test_simple_case(self):
        # Simple case where we have n = 2 and some unary nodes.
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           1
        3       0           1
        4       0           2
        5       0           3
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0       1       2       0
        0       1       3       1
        0       1       4       2,3
        0       1       5       4
        """)
        sites = "position    ancestral_state\n"
        mutations = "site    node    derived_state\n"
        for j in range(5):
            position = j * 1 / 5
            sites += "{} 0\n".format(position)
            mutations += "{} {} 1\n".format(j, j)
        ts = msprime.load_text(
            nodes=nodes, edgesets=edgesets, sites=six.StringIO(sites),
            mutations=six.StringIO(mutations))

        self.assertEqual(ts.sample_size, 2)
        self.assertEqual(ts.num_nodes, 6)
        self.assertEqual(ts.num_trees, 1)
        self.assertEqual(ts.num_sites, 5)
        self.assertEqual(ts.num_mutations, 5)
        self.assertEqual(len(list(ts.diffs())), ts.num_trees)
        t = next(ts.trees())
        self.assertEqual(
            t.parent_dict, {0: 2, 1: 3, 2: 4, 3: 4, 4: 5})
        self.assertEqual(t.mrca(0, 1), 4)
        self.assertEqual(t.mrca(0, 2), 2)
        self.assertEqual(t.mrca(0, 4), 4)
        self.assertEqual(t.mrca(0, 5), 5)
        self.assertEqual(t.mrca(0, 3), 4)
        H = list(ts.haplotypes())
        self.assertEqual(H[0], "10101")
        self.assertEqual(H[1], "01011")

    def test_ladder_tree(self):
        # We have a single tree with a long ladder of unary nodes along a path
        num_unary_nodes = 30
        n = 2
        nodes = """\
            is_sample   time
            1           0
            1           0
        """
        edgesets = """\
            left right parent children
            0    1     2      0
        """
        for j in range(num_unary_nodes + 2):
            nodes += "0 {}\n".format(j + 2)
        for j in range(num_unary_nodes):
            edgesets += "0 1 {} {}\n".format(n + j + 1, n + j)
        root = num_unary_nodes + 3
        root_time = num_unary_nodes + 3
        edgesets += "0    1     {}      1,{}\n".format(root, num_unary_nodes + 2)
        ts = msprime.load_text(six.StringIO(nodes), six.StringIO(edgesets))
        t = next(ts.trees())
        self.assertEqual(t.mrca(0, 1), root)
        self.assertEqual(t.tmrca(0, 1), root_time)
        ts_simplified = ts.simplify()
        self.assertEqual(ts_simplified.num_edgesets, 1)
        t = next(ts_simplified.trees())
        self.assertEqual(t.mrca(0, 1), 2)
        self.assertEqual(t.tmrca(0, 1), root_time)

    def verify_unary_tree_sequence(self, ts):
        """
        Take the specified tree sequence and produce an equivalent in which
        unary records have been interspersed.
        """
        self.assertGreater(ts.num_trees, 2)
        self.assertGreater(ts.num_mutations, 2)
        tables = ts.dump_tables()
        next_node = ts.num_nodes
        added_nodes = []
        node_times = {j: node.time for j, node in enumerate(ts.nodes())}
        edgesets = []
        for e in ts.edgesets():
            node = ts.node(e.parent)
            t = node.time - 1e-14  # Arbitrary small value.
            children = []
            for v in e.children:
                edgesets.append(msprime.Edgeset(
                    left=e.left, right=e.right, parent=next_node, children=(v,)))
                children.append(next_node)
                added_nodes.append((t, node.population))
                node_times[next_node] = t
                next_node += 1
            edgesets.append(msprime.Edgeset(
                left=e.left, right=e.right, parent=e.parent, children=tuple(children)))
        for time, population in added_nodes:
            tables.nodes.add_row(time=time, population=population)
        edgesets.sort(key=lambda e: node_times[e.parent])
        tables.edgesets.reset()
        for e in edgesets:
            tables.edgesets.add_row(
                left=e.left, right=e.right, children=e.children, parent=e.parent)
        ts_new = msprime.load_tables(**tables._asdict())
        self.assertGreater(ts_new.num_edgesets, ts.num_edgesets)
        self.assert_haplotypes_equal(ts, ts_new)
        self.assert_variants_equal(ts, ts_new)
        ts_simplified = ts_new.simplify()
        self.assertEqual(list(ts_simplified.records()), list(ts.records()))
        self.assert_haplotypes_equal(ts, ts_simplified)
        self.assert_variants_equal(ts, ts_simplified)
        self.assertEqual(len(list(ts.diffs())), ts.num_trees)

    def test_binary_tree_sequence_unary_nodes(self):
        ts = msprime.simulate(
            20, recombination_rate=5, mutation_rate=5, random_seed=self.random_seed)
        self.verify_unary_tree_sequence(ts)

    def test_nonbinary_tree_sequence_unary_nodes(self):
        demographic_events = [
            msprime.SimpleBottleneck(time=1.0, proportion=0.95)]
        ts = msprime.simulate(
            20, recombination_rate=10, mutation_rate=5,
            demographic_events=demographic_events, random_seed=self.random_seed)
        found = False
        for r in ts.records():
            if len(r.children) > 2:
                found = True
        self.assertTrue(found)
        self.verify_unary_tree_sequence(ts)


class TestGeneralSamples(TopologyTestCase):
    """
    Test cases in which we have samples at arbitrary nodes (i.e., not at
    {0,...,n - 1}).
    """
    def test_simple_case(self):
        # Simple case where we have n = 3 and samples starting at n.
        nodes = six.StringIO("""\
        id      is_sample   time
        0       0           2
        1       0           1
        2       1           0
        3       1           0
        4       1           0
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0       1       1       2,3
        0       1       0       1,4
        """)
        sites = six.StringIO("""\
        position    ancestral_state
        0.1     0
        0.2     0
        0.3     0
        0.4     0
        """)
        mutations = six.StringIO("""\
        site    node    derived_state
        0       2       1
        1       3       1
        2       4       1
        3       1       1
        """)
        ts = msprime.load_text(
            nodes=nodes, edgesets=edgesets, sites=sites, mutations=mutations)

        self.assertEqual(ts.sample_size, 3)
        self.assertEqual(ts.samples(), [2, 3, 4])
        self.assertEqual(ts.num_nodes, 5)
        self.assertEqual(ts.num_nodes, 5)
        self.assertEqual(ts.num_sites, 4)
        self.assertEqual(ts.num_mutations, 4)
        self.assertEqual(len(list(ts.diffs())), ts.num_trees)
        t = next(ts.trees())
        self.assertEqual(t.root, 0)
        self.assertEqual(t.parent_dict, {1: 0, 2: 1, 3: 1, 4: 0})
        H = list(ts.haplotypes())
        self.assertEqual(H[0], "1001")
        self.assertEqual(H[1], "0101")
        self.assertEqual(H[2], "0010")
        self.assertRaises(_msprime.LibraryError, list, ts.newick_trees())

        tss = ts.simplify()
        # We should have the same tree sequence just with canonicalised nodes.
        self.assertEqual(tss.sample_size, 3)
        self.assertEqual(tss.samples(), [0, 1, 2])
        self.assertEqual(tss.num_nodes, 5)
        self.assertEqual(tss.num_trees, 1)
        self.assertEqual(tss.num_sites, 4)
        self.assertEqual(tss.num_mutations, 4)
        self.assertEqual(len(list(ts.diffs())), ts.num_trees)
        t = next(tss.trees())
        self.assertEqual(t.root, 4)
        self.assertEqual(t.parent_dict, {0: 3, 1: 3, 2: 4, 3: 4})
        H = list(tss.haplotypes())
        self.assertEqual(H[0], "1001")
        self.assertEqual(H[1], "0101")
        self.assertEqual(H[2], "0010")

    def verify_permuted_nodes(self, ts):
        """
        Take the specified tree sequence and permute the nodes, verifying that we
        get back a tree sequence with the correct properties.
        """
        # Mapping from the original nodes into nodes in the new tree sequence.
        node_map = list(range(ts.num_nodes))
        random.shuffle(node_map)
        # Change the permutation so that the relative order of samples is maintained.
        # Then, we should get back exactly the same tree sequence after simplify
        # and haplotypes and variants are also equal.
        samples = sorted(node_map[:ts.sample_size])
        node_map = samples + node_map[ts.sample_size:]
        permuted = permute_nodes(ts, node_map)
        self.assertEqual(permuted.samples(), samples)
        self.assertEqual(list(permuted.haplotypes()), list(ts.haplotypes()))
        self.assertEqual(
            [v.genotypes for v in permuted.variants(as_bytes=True)],
            [v.genotypes for v in ts.variants(as_bytes=True)])
        self.assertEqual(ts.num_trees, permuted.num_trees)
        j = 0
        for t1, t2 in zip(ts.trees(), permuted.trees()):
            t1_dict = {node_map[k]: node_map[v] for k, v in t1.parent_dict.items()}
            self.assertEqual(node_map[t1.root], t2.root)
            self.assertEqual(t1_dict, t2.parent_dict)
            for u1 in t1.nodes():
                u2 = node_map[u1]
                self.assertEqual(
                    sorted([node_map[v] for v in t1.samples(u1)]),
                    sorted(list(t2.samples(u2))))
            j += 1
        self.assertEqual(j, ts.num_trees)

        # The simplified version of the permuted tree sequence should be in canonical
        # form, and identical to the original.
        simplified = permuted.simplify()
        self.assertEqual(simplified.samples(), ts.samples())
        self.assertEqual(list(simplified.nodes()), list(ts.nodes()))
        self.assertEqual(list(simplified.edgesets()), list(ts.edgesets()))
        self.assertEqual(list(simplified.sites()), list(ts.sites()))
        self.assertEqual(list(simplified.haplotypes()), list(ts.haplotypes()))
        self.assertEqual(
            list(simplified.variants(as_bytes=True)), list(ts.variants(as_bytes=True)))

    def test_single_tree_permuted_nodes(self):
        ts = msprime.simulate(10,  mutation_rate=5, random_seed=self.random_seed)
        self.verify_permuted_nodes(ts)

    def test_binary_tree_sequence_permuted_nodes(self):
        ts = msprime.simulate(
            20, recombination_rate=5, mutation_rate=5, random_seed=self.random_seed)
        self.verify_permuted_nodes(ts)

    def test_nonbinary_tree_sequence_permuted_nodes(self):
        demographic_events = [
            msprime.SimpleBottleneck(time=1.0, proportion=0.95)]
        ts = msprime.simulate(
            20, recombination_rate=10, mutation_rate=5,
            demographic_events=demographic_events, random_seed=self.random_seed)
        found = False
        for r in ts.records():
            if len(r.children) > 2:
                found = True
        self.assertTrue(found)
        self.verify_permuted_nodes(ts)


class TestSimplifyExamples(TopologyTestCase):
    """
    Tests for simplify where we write out the input and expected output
    or we detect expected errors.
    """
    def verify_simplify(
            self, samples, filter_invariant_sites=True,
            nodes_before=None, edgesets_before=None, sites_before=None,
            mutations_before=None, nodes_after=None, edgesets_after=None,
            sites_after=None, mutations_after=None, debug=False):
        """
        Verifies that if we run simplify on the specified input we get the
        required output.
        """
        b_nodes = msprime.parse_nodes(six.StringIO(nodes_before))
        b_edgesets = msprime.parse_edgesets(six.StringIO(edgesets_before))
        if sites_before is not None:
            b_sites = msprime.parse_sites(six.StringIO(sites_before))
        else:
            b_sites = msprime.SiteTable()
        if mutations_before is not None:
            b_mutations = msprime.parse_mutations(six.StringIO(mutations_before))
        else:
            b_mutations = msprime.MutationTable()
        msprime.simplify_tables(
            samples=samples, nodes=b_nodes, edgesets=b_edgesets, sites=b_sites,
            mutations=b_mutations, filter_invariant_sites=filter_invariant_sites)
        a_nodes = msprime.parse_nodes(six.StringIO(nodes_after))
        a_edgesets = msprime.parse_edgesets(six.StringIO(edgesets_after))
        if sites_after is not None:
            a_sites = msprime.parse_sites(six.StringIO(sites_after))
        else:
            a_sites = msprime.SiteTable()
        if mutations_after is not None:
            a_mutations = msprime.parse_mutations(six.StringIO(mutations_after))
        else:
            a_mutations = msprime.MutationTable()
        if debug:
            print("nodes required:")
            print(a_nodes)
            print("nodes computed:")
            print(b_nodes)
            print("edgesets required:")
            print(a_edgesets)
            print("edgesets computed:")
            print(b_edgesets)
        self.assertEqual(b_nodes, a_nodes)
        self.assertEqual(b_edgesets, a_edgesets)
        self.assertEqual(b_sites, a_sites)
        self.assertEqual(b_mutations, a_mutations)

    def test_unsorted_edgesets(self):
        # We have two nodes at the same time and interleave edgesets for
        # these nodes together. This is an error because all edgesets for
        # a given parent must be contigous.
        nodes_before = """\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           1
        3       0           1
        """
        edgesets_before = """\
        left    right   parent  children
        0       1       2       0,1
        0       1       3       0,1
        1       2       2       0,1
        1       2       3       0,1
        """
        nodes = msprime.parse_nodes(six.StringIO(nodes_before))
        edgesets = msprime.parse_edgesets(six.StringIO(edgesets_before))
        self.assertRaises(
            _msprime.LibraryError, msprime.simplify_tables,
            samples=[0, 1], nodes=nodes, edgesets=edgesets)

    def test_single_binary_tree(self):
        #
        # 2        4
        #         / \
        # 1      3   \
        #       / \   \
        # 0   (0)(1)  (2)
        nodes_before = """\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           0
        3       0           1
        4       0           2
        """
        edgesets_before = """\
        left    right   parent  children
        0       1       3       0,1
        0       1       4       2,3
        """
        # We sample 0 and 2, so we get
        nodes_after = """\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           2
        """
        edgesets_after = """\
        left    right   parent  children
        0       1       2       0,1
        """
        self.verify_simplify(
            samples=[0, 2],
            nodes_before=nodes_before, edgesets_before=edgesets_before,
            nodes_after=nodes_after, edgesets_after=edgesets_after)

    def test_single_binary_tree_internal_sample(self):
        #
        # 2        4
        #         / \
        # 1     (3)  \
        #       / \   \
        # 0   (0)  1  (2)
        nodes_before = """\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           0
        3       1           1
        4       0           2
        """
        edgesets_before = """\
        left    right   parent  children
        0       1       3       0,1
        0       1       4       2,3
        """
        # We sample 0 and 3, so we get
        nodes_after = """\
        id      is_sample   time
        0       1           0
        1       1           1
        """
        edgesets_after = """\
        left    right   parent  children
        0       1       1       0
        """
        self.verify_simplify(
            samples=[0, 3],
            nodes_before=nodes_before, edgesets_before=edgesets_before,
            nodes_after=nodes_after, edgesets_after=edgesets_after)

    def test_single_binary_tree_internal_sample_meet_at_root(self):
        # 3          5
        #           / \
        # 2        4  (6)
        #         / \
        # 1     (3)  \
        #       / \   \
        # 0   (0)  1   2
        nodes_before = """\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           0
        3       1           1
        4       0           2
        5       0           3
        6       1           2
        """
        edgesets_before = """\
        left    right   parent  children
        0       1       3       0,1
        0       1       4       2,3
        0       1       5       4,6
        """
        # We sample 0 and 3 and 6, so we get
        nodes_after = """\
        id      is_sample   time
        0       1           0
        1       1           1
        2       1           2
        3       0           3
        """
        edgesets_after = """\
        left    right   parent  children
        0       1       1       0
        0       1       3       1,2
        """
        self.verify_simplify(
            samples=[0, 3, 6],
            nodes_before=nodes_before, edgesets_before=edgesets_before,
            nodes_after=nodes_after, edgesets_after=edgesets_after)

    def test_single_binary_tree_simple_mutations(self):
        # 3          5
        #           / \
        # 2        4   \
        #         / \   s0
        # 1      3   s1  \
        #       / \   \   \
        # 0   (0) (1)  2  (6)
        nodes_before = """\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           0
        3       0           1
        4       0           2
        5       0           3
        6       1           0
        """
        edgesets_before = """\
        left    right   parent  children
        0       1       3       0,1
        0       1       4       2,3
        0       1       5       4,6
        """
        sites_before = """\
        id  position    ancestral_state
        0   0.1         0
        1   0.2         0
        """
        mutations_before = """\
        site    node    derived_state
        0       6       1
        1       2       1
        """

        # We sample 0 and 2 and 6, so we get
        nodes_after = """\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           0
        3       0           1
        3       0           3
        """
        edgesets_after = """\
        left    right   parent  children
        0       1       3       0,1
        0       1       4       2,3
        """
        sites_after = """\
        id  position    ancestral_state
        0   0.1         0
        """
        mutations_after = """\
        site    node    derived_state
        0       2       1
        """
        self.verify_simplify(
            samples=[0, 1, 6],
            nodes_before=nodes_before, edgesets_before=edgesets_before,
            sites_before=sites_before, mutations_before=mutations_before,
            nodes_after=nodes_after, edgesets_after=edgesets_after,
            sites_after=sites_after, mutations_after=mutations_after)
        # If we don't filter the fixed sites, we should get the same
        # mutations and the original sites table back.
        self.verify_simplify(
            samples=[0, 1, 6], filter_invariant_sites=False,
            nodes_before=nodes_before, edgesets_before=edgesets_before,
            sites_before=sites_before, mutations_before=mutations_before,
            nodes_after=nodes_after, edgesets_after=edgesets_after,
            sites_after=sites_before, mutations_after=mutations_after)

    def test_overlapping_edgesets(self):
        nodes = """\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           0
        3       0           1
        """
        edgesets_before = """\
        left    right   parent  children
        0       2       3       0,2
        1       3       3       1,2
        """
        # We should resolve the overlapping edgesets here.
        edgesets_after = """\
        left    right   parent  children
        0       1       3       0,2
        1       2       3       0,1,2
        2       3       3       1,2
        """
        self.verify_simplify(
            samples=[0, 1, 2],
            nodes_before=nodes, edgesets_before=edgesets_before,
            nodes_after=nodes, edgesets_after=edgesets_after)

    def test_overlapping_unary_edgesets(self):
        nodes = """\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           1
        """
        edgesets_before = """\
        left    right   parent  children
        0       2       2       0
        1       3       2       1
        """
        # We resolve the overlapping edgesets here. Since the flanking regions
        # have no interesting edges, these are left out of the output.
        edgesets_after = """\
        left    right   parent  children
        1       2       2       0,1
        """
        self.verify_simplify(
            samples=[0, 1],
            nodes_before=nodes, edgesets_before=edgesets_before,
            nodes_after=nodes, edgesets_after=edgesets_after)

    def test_overlapping_unary_edgesets_internal_samples(self):
        nodes = """\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           1
        """
        edgesets_before = """\
        left    right   parent  children
        0       2       2       0
        1       3       2       1
        """
        # We resolve the overlapping edgesets here. Because node 2 is a sample,
        # we should still have the unary edgesets in the output.
        edgesets_after = """\
        left    right   parent  children
        0       1       2       0
        1       2       2       0,1
        2       3       2       1
        """
        self.verify_simplify(
            samples=[0, 1, 2],
            nodes_before=nodes, edgesets_before=edgesets_before,
            nodes_after=nodes, edgesets_after=edgesets_after)

    def test_unary_edgesets_no_overlap(self):
        nodes_before = """\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           1
        """
        edgesets_before = """\
        left    right   parent  children
        0       2       2       0
        2       3       2       1
        """
        # Because there is no overlap between the samples, we just get an
        # empty set of output edgesets.
        nodes_after = """\
        id      is_sample   time
        0       1           0
        1       1           0
        """
        edgesets_after = """\
        left    right   parent  children
        """
        self.verify_simplify(
            samples=[0, 1],
            nodes_before=nodes_before, edgesets_before=edgesets_before,
            nodes_after=nodes_after, edgesets_after=edgesets_after)

    def test_unary_edgesets_no_overlap_internal_sample(self):
        nodes_before = """\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           1
        """
        edgesets_before = """\
        left    right   parent  children
        0       1       2       0
        1       2       2       1
        """
        self.verify_simplify(
            samples=[0, 1, 2],
            nodes_before=nodes_before, edgesets_before=edgesets_before,
            nodes_after=nodes_before, edgesets_after=edgesets_before)


class TestNonSampleExternalNodes(TopologyTestCase):
    """
    Tests for situations in which we have tips that are not samples.
    """
    def test_simple_case(self):
        # Simplest case where we have n = 2 and external non-sample nodes.
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           1
        3       0           0
        4       0           0
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0       1       2       0,1,3,4
        """)
        sites = six.StringIO("""\
        id  position    ancestral_state
        0   0.1         0
        1   0.2         0
        2   0.3         0
        3   0.4         0
        """)
        mutations = six.StringIO("""\
        site    node    derived_state
        0       0       1
        1       1       1
        2       2       1
        3       3       1
        """)
        ts = msprime.load_text(
            nodes=nodes, edgesets=edgesets, sites=sites, mutations=mutations)
        self.assertEqual(ts.sample_size, 2)
        self.assertEqual(ts.num_trees, 1)
        self.assertEqual(ts.num_nodes, 5)
        self.assertEqual(ts.num_sites, 4)
        self.assertEqual(ts.num_mutations, 4)
        t = next(ts.trees())
        self.assertEqual(t.parent_dict, {0: 2, 1: 2, 3: 2, 4: 2})
        self.assertEqual(t.time_dict, {0: 0, 1: 0, 3: 0, 4: 0, 2: 1})
        self.assertEqual(t.root, 2)
        ts_simplified = ts.simplify()
        self.assertEqual(ts_simplified.num_nodes, 3)
        self.assertEqual(ts_simplified.num_trees, 1)
        t = next(ts_simplified.trees())
        self.assertEqual(t.parent_dict, {0: 2, 1: 2})
        self.assertEqual(t.time_dict, {0: 0, 1: 0, 2: 1})
        self.assertEqual(t.root, 2)
        # We should have removed the two non-sample mutations.
        self.assertEqual([s.position for s in t.sites()], [0.1, 0.2])

    def test_unary_non_sample_external_nodes(self):
        # Take an ordinary tree sequence and put a bunch of external non
        # sample nodes on it.
        ts = msprime.simulate(
            15, recombination_rate=5, random_seed=self.random_seed, mutation_rate=5)
        self.assertGreater(ts.num_trees, 2)
        self.assertGreater(ts.num_mutations, 2)
        tables = ts.dump_tables()
        next_node = ts.num_nodes
        tables.edgesets.reset()
        for r in ts.edgesets():
            children = tuple(list(r.children) + [next_node])
            tables.edgesets.add_row(
                left=r.left, right=r.right, parent=r.parent, children=children)
            tables.nodes.add_row(time=0)
            next_node += 1
        ts_new = msprime.load_tables(**tables._asdict())
        self.assertEqual(ts_new.num_nodes, next_node)
        self.assertEqual(ts_new.sample_size, ts.sample_size)
        self.assert_haplotypes_equal(ts, ts_new)
        self.assert_variants_equal(ts, ts_new)
        ts_simplified = ts_new.simplify()
        self.assertEqual(ts_simplified.num_nodes, ts.num_nodes)
        self.assertEqual(ts_simplified.sample_size, ts.sample_size)
        self.assertEqual(list(ts_simplified.records()), list(ts.records()))
        self.assert_haplotypes_equal(ts, ts_simplified)
        self.assert_variants_equal(ts, ts_simplified)


class TestMultipleRoots(TopologyTestCase):
    """
    Tests for situations where we have multiple roots for the samples.
    """
    @unittest.skip("Multiple root simplify")
    def test_simplest_degenerate_case(self):
        # Simplest case where we have n = 2 and two unary records.
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           1
        3       0           1
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0       1       2       0
        0       1       3       1
        """)
        sites = six.StringIO("""\
        id  position    ancestral_state
        0   0.1         0
        1   0.2         0
        """)
        mutations = six.StringIO("""\
        site    node    derived_state
        0       0         1
        1       1         1
        """)
        ts = msprime.load_text(
            nodes=nodes, edgesets=edgesets, sites=sites, mutations=mutations)
        self.assertEqual(ts.num_nodes, 4)
        self.assertEqual(ts.num_trees, 1)
        self.assertEqual(ts.num_sites, 2)
        self.assertEqual(ts.num_mutations, 2)
        t = next(ts.trees())
        self.assertEqual(t.parent_dict, {0: 2, 1: 3})
        self.assertEqual(t.time_dict, {0: 0, 1: 0, 2: 1, 3: 1})
        self.assertEqual(list(ts.haplotypes()), ["10", "01"])
        self.assertEqual(
            [v.genotypes for v in ts.variants(as_bytes=True)], [b"10", b"01"])
        self.assertRaises(_msprime.LibraryError, ts.simplify)

    def test_simplest_non_degenerate_case(self):
        # Simplest case where we have n = 4 and two trees.
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           0
        3       1           0
        4       0           1
        5       0           2
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0       1       4       0,1
        0       1       5       2,3
        """)
        sites = six.StringIO("""\
        id  position    ancestral_state
        0   0.1         0
        1   0.2         0
        2   0.3         0
        3   0.4         0
        """)
        mutations = six.StringIO("""\
        site    node    derived_state
        0       0       1
        1       1       1
        2       2       1
        3       3       1
        """)
        ts = msprime.load_text(
            nodes=nodes, edgesets=edgesets, sites=sites, mutations=mutations)
        self.assertEqual(ts.num_nodes, 6)
        self.assertEqual(ts.num_trees, 1)
        self.assertEqual(ts.num_sites, 4)
        self.assertEqual(ts.num_mutations, 4)
        t = next(ts.trees())
        self.assertEqual(t.parent_dict, {0: 4, 1: 4, 2: 5, 3: 5})
        self.assertEqual(t.time_dict, {0: 0, 1: 0, 2: 0, 3: 0, 4: 1, 5: 2})
        self.assertEqual(list(ts.haplotypes()), ["1000", "0100", "0010", "0001"])
        self.assertEqual(
            [v.genotypes for v in ts.variants(as_bytes=True)],
            [b"1000", b"0100", b"0010", b"0001"])
        self.assertEqual(t.mrca(0, 1), 4)
        self.assertEqual(t.mrca(0, 4), 4)
        self.assertEqual(t.mrca(2, 3), 5)
        self.assertEqual(t.mrca(0, 2), msprime.NULL_NODE)
        self.assertEqual(t.mrca(0, 3), msprime.NULL_NODE)
        self.assertEqual(t.mrca(2, 4), msprime.NULL_NODE)
        ts_simplified = ts.simplify()
        self.assertEqual(ts_simplified.num_nodes, 6)
        self.assertEqual(ts_simplified.num_trees, 1)
        self.assertEqual(ts_simplified.num_sites, 4)
        self.assertEqual(ts_simplified.num_mutations, 4)
        t = next(ts_simplified.trees())
        self.assertEqual(t.parent_dict, {0: 4, 1: 4, 2: 5, 3: 5})
        self.assertEqual(t.time_dict, {0: 0, 1: 0, 2: 0, 3: 0, 4: 1, 5: 2})

    def test_two_reducable_trees(self):
        # We have n = 4 and two trees, with some unary nodes and non-sample samples
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           0
        3       1           0
        4       0           1
        5       0           1
        6       0           2
        7       0           3
        8       0           0   # Non sample sample
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0       1      4         0
        0       1      5         1
        0       1      6         4,5
        0       1      7         2,3,8
        """)
        sites = six.StringIO("""\
        id  position    ancestral_state
        0   0.1         0
        1   0.2         0
        2   0.3         0
        3   0.4         0
        4   0.5         0
        """)
        mutations = six.StringIO("""\
        site    node    derived_state
        0       0       1
        1       1       1
        2       2       1
        3       3       1
        4       8       1
        """)
        ts = msprime.load_text(
            nodes=nodes, edgesets=edgesets, sites=sites, mutations=mutations)
        self.assertEqual(ts.num_nodes, 9)
        self.assertEqual(ts.num_trees, 1)
        self.assertEqual(ts.num_sites, 5)
        self.assertEqual(ts.num_mutations, 5)
        t = next(ts.trees())
        self.assertEqual(t.parent_dict, {0: 4, 1: 5, 2: 7, 3: 7, 4: 6, 5: 6, 8: 7})
        self.assertEqual(
            t.time_dict, {0: 0, 1: 0, 2: 0, 3: 0, 4: 1, 5: 1, 6: 2, 7: 3, 8: 0})
        self.assertEqual(list(ts.haplotypes()), ["10000", "01000", "00100", "00010"])
        self.assertEqual(
            [v.genotypes for v in ts.variants(as_bytes=True)],
            [b"1000", b"0100", b"0010", b"0001", b"0000"])
        self.assertEqual(t.mrca(0, 1), 6)
        self.assertEqual(t.mrca(2, 3), 7)
        self.assertEqual(t.mrca(2, 8), 7)
        self.assertEqual(t.mrca(0, 2), msprime.NULL_NODE)
        self.assertEqual(t.mrca(0, 3), msprime.NULL_NODE)
        self.assertEqual(t.mrca(0, 8), msprime.NULL_NODE)
        ts_simplified = ts.simplify()
        self.assertEqual(ts_simplified.num_nodes, 6)
        self.assertEqual(ts_simplified.num_trees, 1)
        t = next(ts_simplified.trees())
        self.assertEqual(
            list(ts_simplified.haplotypes()), ["1000", "0100", "0010", "0001"])
        self.assertEqual(
            [v.genotypes for v in ts_simplified.variants(as_bytes=True)],
            [b"1000", b"0100", b"0010", b"0001"])
        # The site over the non-sample external node should have been discarded.
        sites = list(t.sites())
        self.assertEqual(sites[-1].position, 0.4)
        self.assertEqual(t.parent_dict, {0: 4, 1: 4, 2: 5, 3: 5})
        self.assertEqual(t.time_dict, {0: 0, 1: 0, 2: 0, 3: 0, 4: 2, 5: 3})

    def test_one_reducable_tree(self):
        # We have n = 4 and two trees. One tree is reducable and the other isn't.
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           0
        3       1           0
        4       0           1
        5       0           1
        6       0           2
        7       0           3
        8       0           0   # Non sample sample
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0       1      4         0
        0       1      5         1
        0       1      6         4,5
        0       1      7         2,3,8
        """)
        ts = msprime.load_text(nodes=nodes, edgesets=edgesets)
        self.assertEqual(ts.num_nodes, 9)
        self.assertEqual(ts.num_trees, 1)
        t = next(ts.trees())
        self.assertEqual(t.parent_dict, {0: 4, 1: 5, 2: 7, 3: 7, 4: 6, 5: 6, 8: 7})
        self.assertEqual(
            t.time_dict, {0: 0, 1: 0, 2: 0, 3: 0, 4: 1, 5: 1, 6: 2, 7: 3, 8: 0})
        self.assertEqual(t.mrca(0, 1), 6)
        self.assertEqual(t.mrca(2, 3), 7)
        self.assertEqual(t.mrca(2, 8), 7)
        self.assertEqual(t.mrca(0, 2), msprime.NULL_NODE)
        self.assertEqual(t.mrca(0, 3), msprime.NULL_NODE)
        self.assertEqual(t.mrca(0, 8), msprime.NULL_NODE)
        ts_simplified = ts.simplify()
        self.assertEqual(ts_simplified.num_nodes, 6)
        self.assertEqual(ts_simplified.num_trees, 1)
        t = next(ts_simplified.trees())
        self.assertEqual(t.parent_dict, {0: 4, 1: 4, 2: 5, 3: 5})
        self.assertEqual(t.time_dict, {0: 0, 1: 0, 2: 0, 3: 0, 4: 2, 5: 3})

    @unittest.skip("Simplify with root mutations")
    # NOTE: This test has not been checked since updating to the text representation
    # so there might be other problems with it.
    def test_mutations_over_roots(self):
        # Mutations over root nodes should be ok when we have multiple roots.
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           0
        3       0           1
        4       0           2
        5       0           2
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0       1       3       0,1
        0       1       4       3
        0       1       5       2
        """)
        sites = six.StringIO("""\
        id  position    ancestral_state
        0   0.1         0
        1   0.2         0
        2   0.3         0
        3   0.4         0
        4   0.5         0
        5   0.6         0
        """)
        mutations = six.StringIO("""\
        site    node    derived_state
        0       0       1
        1       1       1
        2       3       1
        3       4       1
        4       2       1
        5       5       1
        """)
        ts = msprime.load_text(
            nodes=nodes, edgesets=edgesets, sites=sites, mutations=mutations)
        self.assertEqual(ts.num_nodes, 6)
        self.assertEqual(ts.num_trees, 1)
        self.assertEqual(ts.num_sites, 6)
        self.assertEqual(ts.num_mutations, 6)
        t = next(ts.trees())
        self.assertEqual(len(list(t.sites())), 6)
        haplotypes = ["101100", "011100", "000011"]
        variants = [b"100", b"010", b"110", b"110", b"001", b"001"]
        self.assertEqual(list(ts.haplotypes()), haplotypes)
        self.assertEqual([v.genotypes for v in ts.variants(as_bytes=True)], variants)
        ts_simplified = ts.simplify(filter_root_mutations=False)

        tables = ts_simplified.dump_tables()
        print()
        print(tables.sites)
        print(tables.mutations)
        self.assertEqual(list(ts_simplified.haplotypes()), haplotypes)
        self.assertEqual(
            [v.genotypes for v in ts_simplified.variants(as_bytes=True)], variants)
        ts_simplified = ts.simplify(filter_root_mutations=True)
        self.assertEqual(list(ts_simplified.haplotypes()), ["10", "01", "00"])
        self.assertEqual(
            [v.genotypes for v in ts_simplified.variants(as_bytes=True)],
            [b"100", b"010"])

    def test_break_single_tree(self):
        # Take a single largish tree from msprime, and remove the oldest record.
        # This breaks it into two subtrees.
        ts = msprime.simulate(20, random_seed=self.random_seed, mutation_rate=4)
        self.assertGreater(ts.num_mutations, 5)
        tables = ts.dump_tables()
        tables.edgesets.set_columns(
            left=tables.edgesets.left[:-1], right=tables.edgesets.right[:-1],
            parent=tables.edgesets.parent[:-1],
            children_length=tables.edgesets.children_length[:-1],
            children=tables.edgesets.children[:-tables.edgesets.children_length[-1]])
        ts_new = msprime.load_tables(**tables._asdict())
        self.assertEqual(ts.sample_size, ts_new.sample_size)
        self.assertEqual(ts.num_edgesets, ts_new.num_edgesets + 1)
        self.assertEqual(ts.num_trees, ts_new.num_trees)
        self.assert_haplotypes_equal(ts, ts_new)
        self.assert_variants_equal(ts, ts_new)
        roots = set()
        t_new = next(ts_new.trees())
        for u in ts_new.samples():
            while t_new.parent(u) != msprime.NULL_NODE:
                u = t_new.parent(u)
            roots.add(u)
        self.assertEqual(len(roots), 2)
        self.assertIn(t_new.root, roots)


class TestWithVisuals(TopologyTestCase):
    """
    Some pedantic tests with ascii depictions of what's supposed to happen.
    """

    def verify_simplify_topology(self, ts, sample, haplotypes=False):
        # copies from test_highlevel.py
        new_ts = ts.simplify(sample)
        sample_map = {k: j for j, k in enumerate(sample)}
        old_trees = ts.trees()
        old_tree = next(old_trees)
        self.assertGreaterEqual(ts.get_num_trees(), new_ts.get_num_trees())
        for new_tree in new_ts.trees():
            new_left, new_right = new_tree.get_interval()
            old_left, old_right = old_tree.get_interval()
            # Skip ahead on the old tree until new_left is within its interval
            while old_right <= new_left:
                old_tree = next(old_trees)
                old_left, old_right = old_tree.get_interval()
            # If the TMRCA of all pairs of samples is the same, then we have the
            # same information. We limit this to at most 500 pairs
            pairs = itertools.islice(itertools.combinations(sample, 2), 500)
            for pair in pairs:
                mapped_pair = [sample_map[u] for u in pair]
                mrca1 = old_tree.get_mrca(*pair)
                mrca2 = new_tree.get_mrca(*mapped_pair)
                self.assertEqual(old_tree.get_time(mrca1), new_tree.get_time(mrca2))
                self.assertEqual(
                    old_tree.get_population(mrca1), new_tree.get_population(mrca2))
        if haplotypes:
            orig_haps = list(ts.haplotypes())
            simp_haps = list(new_ts.haplotypes())
            for i, j in enumerate(sample):
                self.assertEqual(orig_haps[j], simp_haps[i])

    def test_partial_non_sample_external_nodes(self):
        # A somewhat more complicated test case with a partially specified,
        # non-sampled tip.
        #
        # Here is the situation:
        #
        # 1.0             7
        # 0.7            / \                                            6
        #               /   \                                          / \
        # 0.5          /     5                      5                 /   5
        #             /     / \                    / \               /   / \
        # 0.4        /     /   4                  /   4             /   /   4
        #           /     /   / \                /   / \           /   /   / \
        #          /     /   3   \              /   /   \         /   /   3   \
        #         /     /         \            /   /     \       /   /         \
        # 0.0    0     1           2          1   0       2     0   1           2
        #
        #          (0.0, 0.2),                 (0.2, 0.8),         (0.8, 1.0)

        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           0
        3       0           0.2  # Non sample sample
        4       0           0.4
        5       0           0.5
        6       0           0.7
        7       0           1.0
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0.0     0.2     4       2,3
        0.2     0.8     4       0,2
        0.8     1.0     4       2,3
        0.0     1.0     5       1,4
        0.8     1.0     6       0,5
        0.0     0.2     7       0,5
        """)
        true_trees = [
            {0: 7, 1: 5, 2: 4, 3: 4, 4: 5, 5: 7, 6: -1, 7: -1},
            {0: 4, 1: 5, 2: 4, 3: -1, 4: 5, 5: -1, 6: -1, 7: -1},
            {0: 6, 1: 5, 2: 4, 3: 4, 4: 5, 5: 6, 6: -1, 7: -1}]
        ts = msprime.load_text(nodes=nodes, edgesets=edgesets)
        tree_dicts = [t.parent_dict for t in ts.trees()]
        self.assertEqual(ts.sample_size, 3)
        self.assertEqual(ts.num_trees, 3)
        self.assertEqual(ts.num_nodes, 8)
        # check topologies agree:
        for a, t in zip(true_trees, tree_dicts):
            for k in a.keys():
                if k in t.keys():
                    self.assertEqual(t[k], a[k])
                else:
                    self.assertEqual(a[k], msprime.NULL_NODE)
        # check .simplify() works here
        self.verify_simplify_topology(ts, [0, 1, 2])

    def test_partial_non_sample_external_nodes_2(self):
        # The same situation as above, but partial tip is labeled '7' not '3':
        #
        # 1.0          6
        # 0.7         / \                                       5
        #            /   \                                     / \
        # 0.5       /     4                 4                 /   4
        #          /     / \               / \               /   / \
        # 0.4     /     /   3             /   3             /   /   3
        #        /     /   / \           /   / \           /   /   / \
        #       /     /   7   \         /   /   \         /   /   7   \
        #      /     /         \       /   /     \       /   /         \
        # 0.0 0     1           2     1   0       2     0   1           2
        #
        #          (0.0, 0.2),         (0.2, 0.8),         (0.8, 1.0)
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           0
        3       0           0.4
        4       0           0.5
        5       0           0.7
        6       0           1.0
        7       0           0    # Non sample sample
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0.0     0.2     3       2,7
        0.2     0.8     3       0,2
        0.8     1.0     3       2,7
        0.0     0.2     4       1,3
        0.2     0.8     4       1,3
        0.8     1.0     4       1,3
        0.8     1.0     5       0,4
        0.0     0.2     6       0,4
        """)
        true_trees = [
            {0: 6, 1: 4, 2: 3, 3: 4, 4: 6, 5: -1, 6: -1, 7: 3},
            {0: 3, 1: 4, 2: 3, 3: 4, 4: -1, 5: -1, 6: -1, 7: -1},
            {0: 5, 1: 4, 2: 3, 3: 4, 4: 5, 5: -1, 6: -1, 7: 3}]
        ts = msprime.load_text(nodes=nodes, edgesets=edgesets)
        tree_dicts = [t.parent_dict for t in ts.trees()]
        # sample size check works here since 7 > 3
        self.assertEqual(ts.sample_size, 3)
        self.assertEqual(ts.num_trees, 3)
        self.assertEqual(ts.num_nodes, 8)
        # check topologies agree:
        for a, t in zip(true_trees, tree_dicts):
            for k in a.keys():
                if k in t.keys():
                    self.assertEqual(t[k], a[k])
                else:
                    self.assertEqual(a[k], msprime.NULL_NODE)
        self.verify_simplify_topology(ts, [0, 1, 2])

    def test_single_offspring_records(self):
        # Here we have inserted a single-offspring record
        # (for 6 on the left segment):
        #
        # 1.0             7
        # 0.7            / 6                                                  6
        #               /   \                                                / \
        # 0.5          /     5                       5                      /   5
        #             /     / \                     / \                    /   / \
        # 0.4        /     /   4                   /   4                  /   /   4
        # 0.3       /     /   / \                 /   / \                /   /   / \
        #          /     /   3   \               /   /   \              /   /   3   \
        #         /     /         \             /   /     \            /   /         \
        # 0.0    0     1           2           1   0       2          0   1           2
        #
        #          (0.0, 0.2),               (0.2, 0.8),              (0.8, 1.0)
        nodes = six.StringIO("""\
        id  is_sample   time
        0   1           0
        1   1           0
        2   1           0
        3   0           0       # Non sample sample
        4   0           0.4
        5   0           0.5
        6   0           0.7
        7   0           1.0
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0.0     0.2     4       2,3
        0.2     0.8     4       0,2
        0.8     1.0     4       2,3
        0.0     1.0     5       1,4
        0.8     1.0     6       0,5
        0.0     0.2     6       5
        0.0     0.2     7       0,6
        """)
        ts = msprime.load_text(nodes, edgesets)
        true_trees = [
            {0: 7, 1: 5, 2: 4, 3: 4, 4: 5, 5: 6, 6: 7, 7: -1},
            {0: 4, 1: 5, 2: 4, 3: -1, 4: 5, 5: -1, 6: -1, 7: -1},
            {0: 6, 1: 5, 2: 4, 3: 4, 4: 5, 5: 6, 6: -1, 7: -1}]
        tree_dicts = [t.parent_dict for t in ts.trees()]
        self.assertEqual(ts.sample_size, 3)
        self.assertEqual(ts.num_trees, 3)
        self.assertEqual(ts.num_nodes, 8)
        # check topologies agree:
        for a, t in zip(true_trees, tree_dicts):
            for k in a.keys():
                if k in t.keys():
                    self.assertEqual(t[k], a[k])
                else:
                    self.assertEqual(a[k], msprime.NULL_NODE)
        self.verify_simplify_topology(ts, [0, 1, 2])

    @unittest.skip("Complex mutations for simplify")
    def test_many_single_offspring(self):
        # a more complex test with single offspring
        # With `(i,j,x)->k` denoting that individual `k` inherits from `i` on `[0,x)`
        #    and from `j` on `[x,1)`:
        # 1. Begin with an individual `3` (and another anonymous one) at `t=0`.
        # 2. `(3,?,1.0)->4` and `(3,?,1.0)->5` at `t=1`
        # 3. `(4,3,0.9)->6` and `(3,5,0.1)->7` and then `3` dies at `t=2`
        # 4. `(6,7,0.7)->8` at `t=3`
        # 5. `(8,6,0.8)->9` and `(7,8,0.2)->10` at `t=4`.
        # 6. `(3,9,0.6)->0` and `(9,10,0.5)->1` and `(10,4,0.4)->2` at `t=5`.
        # 7. We sample `0`, `1`, and `2`.
        # Here are the trees:
        # t                  |              |              |             |
        #
        # 0       --3--      |     --3--    |     --3--    |    --3--    |    --3--
        #        /  |  \     |    /  |  \   |    /     \   |   /     \   |   /     \
        # 1     4   |   5    |   4   *   5  |   4       5  |  4       5  |  4       5
        #       |\ / \ /|    |   |\   \     |   |\     /   |  |\     /   |  |\     /|
        # 2     | 6   7 |    |   | 6   7    |   | 6   7    |  | 6   7    |  | 6   7 |
        #       | |\ /| |    |   |  \  *    |   |  \  |    |  |  *       |  |  *    | ...
        # 3     | | 8 | |    |   |   8 |    |   *   8 *    |  |   8      |  |   8   |
        #       | |/ \| |    |   |  /  |    |   |  /  |    |  |  * *     |  |  / \  |
        # 4     | 9  10 |    |   | 9  10    |   | 9  10    |  | 9  10    |  | 9  10 |
        #       |/ \ / \|    |   |  \   *   |   |  \   \   |  |  \   *   |  |  \    |
        # 5     0   1   2    |   0   1   2  |   0   1   2  |  0   1   2  |  0   1   2
        #
        #                    |   0.0 - 0.1  |   0.1 - 0.2  |  0.2 - 0.4  |  0.4 - 0.5
        # ... continued:
        # t                  |             |             |             |
        #
        # 0         --3--    |    --3--    |    --3--    |    --3--    |    --3--
        #          /     \   |   /     \   |   /     \   |   /     \   |   /  |  \
        # 1       4       5  |  4       5  |  4       5  |  4       5  |  4   |   5
        #         |\     /|  |   \     /|  |   \     /|  |   \     /|  |     /   /|
        # 2       | 6   7 |  |    6   7 |  |    6   7 |  |    6   7 |  |    6   7 |
        #         |  \    |  |     \    |  |       /  |  |    |  /  |  |    |  /  |
        # 3  ...  |   8   |  |      8   |  |      8   |  |    | 8   |  |    | 8   |
        #         |  / \  |  |     / \  |  |     / \  |  |    |  \  |  |    |  \  |
        # 4       | 9  10 |  |    9  10 |  |    9  10 |  |    9  10 |  |    9  10 |
        #         |    /  |  |   /   /  |  |   /   /  |  |   /   /  |  |   /   /  |
        # 5       0   1   2  |  0   1   2  |  0   1   2  |  0   1   2  |  0   1   2
        #
        #         0.5 - 0.6  |  0.6 - 0.7  |  0.7 - 0.8  |  0.8 - 0.9  |  0.9 - 1.0

        true_trees = [
            {0: 4, 1: 9, 2: 10, 3: -1, 4: 3, 5: 3, 6: 4, 7: 3, 8: 6, 9: 8, 10: 7},
            {0: 4, 1: 9, 2: 10, 3: -1, 4: 3, 5: 3, 6: 4, 7: 5, 8: 6, 9: 8, 10: 7},
            {0: 4, 1: 9, 2: 10, 3: -1, 4: 3, 5: 3, 6: 4, 7: 5, 8: 6, 9: 8, 10: 8},
            {0: 4, 1: 9,  2: 5, 3: -1, 4: 3, 5: 3, 6: 4, 7: 5, 8: 6, 9: 8, 10: 8},
            {0: 4, 1: 10, 2: 5, 3: -1, 4: 3, 5: 3, 6: 4, 7: 5, 8: 6, 9: 8, 10: 8},
            {0: 9, 1: 10, 2: 5, 3: -1, 4: 3, 5: 3, 6: 4, 7: 5, 8: 6, 9: 8, 10: 8},
            {0: 9, 1: 10, 2: 5, 3: -1, 4: 3, 5: 3, 6: 4, 7: 5, 8: 7, 9: 8, 10: 8},
            {0: 9, 1: 10, 2: 5, 3: -1, 4: 3, 5: 3, 6: 4, 7: 5, 8: 7, 9: 6, 10: 8},
            {0: 9, 1: 10, 2: 5, 3: -1, 4: 3, 5: 3, 6: 3, 7: 5, 8: 7, 9: 6, 10: 8}
        ]
        true_haplotypes = ['0100', '0001', '1110']
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           0
        3       0           5
        4       0           4
        5       0           4
        6       0           3
        7       0           3
        8       0           2
        9       0           1
        10      0           1
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0.5     1.0     10      1
        0.0     0.4     10      2
        0.6     1.0     9       0
        0.0     0.5     9       1
        0.8     1.0     8       10
        0.2     0.8     8       9,10
        0.0     0.2     8       9
        0.7     1.0     7       8
        0.0     0.2     7       10
        0.8     1.0     6       9
        0.0     0.7     6       8
        0.4     1.0     5       2,7
        0.1     0.4     5       7
        0.6     0.9     4       6
        0.0     0.6     4       0,6
        0.9     1.0     3       4,5,6
        0.1     0.9     3       4,5
        0.0     0.1     3       4,5,7
        """)
        sites = six.StringIO("""\
        position    ancestral_state
        0.05        0
        0.15        0
        0.25        0
        0.4         0
        """)
        mutations = six.StringIO("""\
        site    node    derived_state
        0       7       1
        0      10       0
        0       2       1
        1       0       1
        1      10       1
        2       8       1
        2       9       0
        2      10       0
        2       2       1
        3       8       1
        """)
        ts = msprime.load_text(nodes, edgesets, sites, mutations)
        tree_dicts = [t.parent_dict for t in ts.trees()]
        self.assertEqual(ts.sample_size, 3)
        self.assertEqual(ts.num_trees, len(true_trees))
        self.assertEqual(ts.num_nodes, 11)
        self.assertEqual(len(list(ts.diffs())), ts.num_trees)
        # check topologies agree:
        for a, t in zip(true_trees, tree_dicts):
            for k in a.keys():
                if k in t.keys():
                    self.assertEqual(t[k], a[k])
                else:
                    self.assertEqual(a[k], msprime.NULL_NODE)
        for j, x in enumerate(ts.haplotypes()):
            self.assertEqual(x, true_haplotypes[j])
        self.verify_simplify_topology(ts, [0, 1, 2], haplotypes=True)
        self.verify_simplify_topology(ts, [1, 0, 2], haplotypes=True)
        self.verify_simplify_topology(ts, [0, 1], haplotypes=False)
        self.verify_simplify_topology(ts, [1, 2], haplotypes=False)
        self.verify_simplify_topology(ts, [2, 0], haplotypes=False)

    def test_tricky_switches(self):
        # suppose the topology has:
        # left right parent children
        #  0.0   0.5      6      0,1
        #  0.5   1.0      6      4,5
        #  0.0   0.4      7      2,3
        #
        # --------------------------
        #
        #        12         .        12         .        12         .
        #       /  \        .       /  \        .       /  \        .
        #     11    \       .      /    \       .      /    \       .
        #     / \    \      .     /     10      .     /     10      .
        #    /   \    \     .    /     /  \     .    /     /  \     .
        #   6     7    8    .   6     9    8    .   6     9    8    .
        #  / \   / \   /\   .  / \   / \   /\   .  / \   / \   /\   .
        # 0   1 2   3 4  5  . 0   1 2   3 4  5  . 4   5 2   3 0  1  .
        #                   .                   .                   .
        # 0.0              0.4                 0.5                 1.0
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           0
        3       1           0
        4       1           0
        5       1           0
        6       0           1
        7       0           1
        8       0           1
        9       0           1
        10      0           2
        11      0           3
        12      0           4
        """)
        edgesets = six.StringIO("""\
        left right parent children
        0.0  0.5   6      0,1
        0.5  1.0   6      4,5
        0.0  0.4   7      2,3
        0.0  0.5   8      4,5
        0.5  1.0   8      0,1
        0.4  1.0   9      2,3
        0.4  1.0   10     8,9
        0.0  0.4   11     6,7
        0.0  0.4   12     8,11
        0.4  1.0   12     6,10
        """)
        true_trees = [
                {0: 6, 1: 6, 2: 7, 3: 7, 4: 8, 5: 8, 6: 11,
                    7: 11, 8: 12, 9: -1, 10: -1, 11: 12, 12: -1},
                {0: 6, 1: 6, 2: 9, 3: 9, 4: 8, 5: 8, 6: 12,
                    7: -1, 8: 10, 9: 10, 10: 12, 11: -1, 12: -1},
                {0: 8, 1: 8, 2: 9, 3: 9, 4: 6, 5: 6, 6: 12,
                    7: -1, 8: 10, 9: 10, 10: 12, 11: -1, 12: -1}
        ]
        ts = msprime.load_text(nodes, edgesets)
        tree_dicts = [t.parent_dict for t in ts.trees()]
        self.assertEqual(ts.sample_size, 6)
        self.assertEqual(ts.num_trees, len(true_trees))
        self.assertEqual(ts.num_nodes, 13)
        self.assertEqual(len(list(ts.diffs())), ts.num_trees)
        # check topologies agree:
        for a, t in zip(true_trees, tree_dicts):
            for k in a.keys():
                if k in t.keys():
                    self.assertEqual(t[k], a[k])
                else:
                    self.assertEqual(a[k], msprime.NULL_NODE)
        self.verify_simplify_topology(ts, [0, 2])
        self.verify_simplify_topology(ts, [0, 4])
        self.verify_simplify_topology(ts, [2, 4])

    def test_tricky_simplify(self):
        # Continue as above but invoke simplfy:
        #
        #         12         .          12         .
        #        /  \        .         /  \        .
        #      11    \       .       11    \       .
        #      / \    \      .       / \    \      .
        #    13   \    \     .      /  15    \     .
        #    / \   \    \    .     /   / \    \    .
        #   6  14   7    8   .    6  14   7    8   .
        #  / \     / \   /\  .   / \     / \   /\  .
        # 0   1   2   3 4  5 .  0   1   2   3 4  5 .
        #                    .                     .
        # 0.0               0.1                   0.4
        #
        #  .        12         .        12         .
        #  .       /  \        .       /  \        .
        #  .      /    \       .      /    \       .
        #  .     /     10      .     /     10      .
        #  .    /     /  \     .    /     /  \     .
        #  .   6     9    8    .   6     9    8    .
        #  .  / \   / \   /\   .  / \   / \   /\   .
        #  . 0   1 2   3 4  5  . 4   5 2   3 0  1  .
        #  .                   .                   .
        # 0.4                 0.5                 1.0
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           0
        3       1           0
        4       1           0
        5       1           0
        6       0           1
        7       0           1
        8       0           1
        9       0           1
        10      0           2
        11      0           3
        12      0           4
        13      0           2
        14      0           1
        15      0           2
        """)
        edgesets = six.StringIO("""\
        left right parent children
        0.0  0.5   6      0,1
        0.5  1.0   6      4,5
        0.0  0.4   7      2,3
        0.0  0.5   8      4,5
        0.5  1.0   8      0,1
        0.4  1.0   9      2,3
        0.4  1.0   10     8,9
        0.0  0.1   13     6,14
        0.1  0.4   15     7,14
        0.0  0.1   11     7,13
        0.1  0.4   11     6,15
        0.0  0.4   12     8,11
        0.4  1.0   12     6,10
        """)
        true_trees = [
                {0: 6, 1: 6, 2: 7, 3: 7, 4: 8, 5: 8, 6: 11,
                    7: 11, 8: 12, 9: -1, 10: -1, 11: 12, 12: -1},
                {0: 6, 1: 6, 2: 9, 3: 9, 4: 8, 5: 8, 6: 12,
                    7: -1, 8: 10, 9: 10, 10: 12, 11: -1, 12: -1},
                {0: 8, 1: 8, 2: 9, 3: 9, 4: 6, 5: 6, 6: 12,
                    7: -1, 8: 10, 9: 10, 10: 12, 11: -1, 12: -1}
        ]
        big_ts = msprime.load_text(nodes, edgesets)
        self.assertEqual(big_ts.num_trees, 1+len(true_trees))
        self.assertEqual(big_ts.num_nodes, 16)
        ts = big_ts.simplify()
        self.assertEqual(ts.sample_size, 6)
        self.assertEqual(ts.num_nodes, 13)

    def test_ancestral_samples(self):
        # Check that specifying samples to be not at time 0.0 works.
        #
        # 1.0             7
        # 0.7            / \                      8                     6
        #               /   \                    / \                   / \
        # 0.5          /     5                  /   5                 /   5
        #             /     / \                /   / \               /   / \
        # 0.4        /     /   4              /   /   4             /   /   4
        #           /     /   / \            /   /   / \           /   /   / \
        # 0.2      /     /   3   \          3   /   /   \         /   /   3   \
        #         /     /    *    \         *  /   /     \       /   /    *    \
        # 0.0    0     1           2          1   0       2     0   1           2
        #              *           *          *           *         *           *
        #          (0.0, 0.2),                 (0.2, 0.8),         (0.8, 1.0)
        #
        # Simplified, keeping [1,2,3]
        #
        # 1.0
        # 0.7                                     5
        #                                        / \
        # 0.5                4                  /   4                     4
        #                   / \                /   / \                   / \
        # 0.4              /   3              /   /   3                 /   3
        #                 /   / \            /   /     \               /   / \
        # 0.2            /   2   \          2   /       \             /   2   \
        #               /    *    \         *  /         \           /    *    \
        # 0.0          0           1          0           1         0           1
        #              *           *          *           *         *           *
        #          (0.0, 0.2),                 (0.2, 0.8),         (0.8, 1.0)

        nodes = six.StringIO("""\
        id      is_sample   time
        0       0           0
        1       1           0
        2       1           0
        3       1           0.2
        4       0           0.4
        5       0           0.5
        6       0           0.7
        7       0           1.0
        8       0           0.8
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0.0     0.2     4       2,3
        0.2     0.8     4       0,2
        0.8     1.0     4       2,3
        0.0     1.0     5       1,4
        0.8     1.0     6       0,5
        0.2     0.8     8       3,5
        0.0     0.2     7       0,5
        """)
        first_ts = msprime.load_text(nodes=nodes, edgesets=edgesets)
        ts = first_ts.simplify()
        true_trees = [
            {0: 7, 1: 5, 2: 4, 3: 4, 4: 5, 5: 7, 6: -1, 7: -1},
            {0: 4, 1: 5, 2: 4, 3: 8, 4: 5, 5: 8, 6: -1, 7: -1},
            {0: 6, 1: 5, 2: 4, 3: 4, 4: 5, 5: 6, 6: -1, 7: -1}]
        # maps [1,2,3] -> [0,1,2]
        true_simplified_trees = [
            {0: 4, 1: 3, 2: 3, 3: 4},
            {0: 4, 1: 4, 2: 5, 4: 5},
            {0: 4, 1: 3, 2: 3, 3: 4}]
        self.assertEqual(first_ts.sample_size, 3)
        self.assertEqual(ts.sample_size, 3)
        self.assertEqual(first_ts.num_trees, 3)
        self.assertEqual(ts.num_trees, 3)
        self.assertEqual(first_ts.num_nodes, 9)
        self.assertEqual(ts.num_nodes, 6)
        self.assertEqual(first_ts.time(3), 0.2)
        self.assertEqual(ts.time(2), 0.2)
        # check topologies agree:
        tree_dicts = [t.parent_dict for t in first_ts.trees()]
        for a, t in zip(true_trees, tree_dicts):
            for k in a.keys():
                if k in t.keys():
                    self.assertEqual(t[k], a[k])
                else:
                    self.assertEqual(a[k], msprime.NULL_NODE)
        tree_simplified_dicts = [t.parent_dict for t in ts.trees()]
        for a, t in zip(true_simplified_trees, tree_simplified_dicts):
            for k in a.keys():
                if k in t.keys():
                    self.assertEqual(t[k], a[k])
                else:
                    self.assertEqual(a[k], msprime.NULL_NODE)
        # check .simplify() works here
        self.verify_simplify_topology(first_ts, [1, 2, 3])

    def test_all_ancestral_samples(self):
        # Check that specifying samples all to be not at time 0.0 works.
        #
        # 1.0             7
        # 0.7            / \                      8                     6
        #               /   \                    / \                   / \
        # 0.5          /     5                  /   5                 /   5
        #             /     / \                /   / \               /   / \
        # 0.4        /     /   4              /   /   4             /   /   4
        #           /     /   / \            /   /   / \           /   /   / \
        # 0.2      /     /   3   \          3   /   /   \         /   /   3   \
        #         /     1    *    2         *  1   /     2       /   1    *    2
        # 0.0    0      *         *            *  0      *      0    *         *
        #
        #          (0.0, 0.2),                 (0.2, 0.8),         (0.8, 1.0)

        nodes = six.StringIO("""\
        id      is_sample   time
        0       0           0
        1       1           0.1
        2       1           0.1
        3       1           0.2
        4       0           0.4
        5       0           0.5
        6       0           0.7
        7       0           1.0
        8       0           0.8
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0.0     0.2     4       2,3
        0.2     0.8     4       0,2
        0.8     1.0     4       2,3
        0.0     1.0     5       1,4
        0.8     1.0     6       0,5
        0.2     0.8     8       3,5
        0.0     0.2     7       0,5
        """)
        ts = msprime.load_text(nodes=nodes, edgesets=edgesets)
        true_trees = [
            {0: 7, 1: 5, 2: 4, 3: 4, 4: 5, 5: 7, 6: -1, 7: -1},
            {0: 4, 1: 5, 2: 4, 3: 8, 4: 5, 5: 8, 6: -1, 7: -1},
            {0: 6, 1: 5, 2: 4, 3: 4, 4: 5, 5: 6, 6: -1, 7: -1}]
        self.assertEqual(ts.sample_size, 3)
        self.assertEqual(ts.num_trees, 3)
        self.assertEqual(ts.num_nodes, 9)
        self.assertEqual(ts.time(0), 0.0)
        self.assertEqual(ts.time(1), 0.1)
        self.assertEqual(ts.time(2), 0.1)
        self.assertEqual(ts.time(3), 0.2)
        # check topologies agree:
        tree_dicts = [t.parent_dict for t in ts.trees()]
        for a, t in zip(true_trees, tree_dicts):
            for k in a.keys():
                if k in t.keys():
                    self.assertEqual(t[k], a[k])
                else:
                    self.assertEqual(a[k], msprime.NULL_NODE)
        # check .simplify() works here
        self.verify_simplify_topology(ts, [1, 2, 3])

    def test_internal_sampled_node(self):
        # 1.0             7
        # 0.7            / \                      8                     6
        #               /   \                    / \                   / \
        # 0.5          /     5                  /   5                 /   5
        #             /     /*\                /   /*\               /   /*\
        # 0.4        /     /   4              /   /   4             /   /   4
        #           /     /   / \            /   /   / \           /   /   / \
        # 0.2      /     /   3   \          3   /   /   \         /   /   3   \
        #         /     1    *    2         *  1   /     2       /   1    *    2
        # 0.0    0      *         *            *  0      *      0    *         *
        #
        #          (0.0, 0.2),                 (0.2, 0.8),         (0.8, 1.0)
        nodes = six.StringIO("""\
        id      is_sample   time
        0       0           0
        1       1           0.1
        2       1           0.1
        3       1           0.2
        4       0           0.4
        5       1           0.5
        6       0           0.7
        7       0           1.0
        8       0           0.8
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0.0     0.2     4       2,3
        0.2     0.8     4       0,2
        0.8     1.0     4       2,3
        0.0     1.0     5       1,4
        0.8     1.0     6       0,5
        0.2     0.8     8       3,5
        0.0     0.2     7       0,5
        """)
        ts = msprime.load_text(nodes=nodes, edgesets=edgesets)
        true_trees = [
            {0: 7, 1: 5, 2: 4, 3: 4, 4: 5, 5: 7, 6: -1, 7: -1},
            {0: 4, 1: 5, 2: 4, 3: 8, 4: 5, 5: 8, 6: -1, 7: -1},
            {0: 6, 1: 5, 2: 4, 3: 4, 4: 5, 5: 6, 6: -1, 7: -1}]
        self.assertEqual(ts.sample_size, 4)
        self.assertEqual(ts.num_trees, 3)
        self.assertEqual(ts.num_nodes, 9)
        self.assertEqual(ts.time(0), 0.0)
        self.assertEqual(ts.time(1), 0.1)
        self.assertEqual(ts.time(2), 0.1)
        self.assertEqual(ts.time(3), 0.2)
        # check topologies agree:
        tree_dicts = [t.parent_dict for t in ts.trees()]
        for a, t in zip(true_trees, tree_dicts):
            for k in a.keys():
                if k in t.keys():
                    self.assertEqual(t[k], a[k])
                else:
                    self.assertEqual(a[k], msprime.NULL_NODE)
        # check .simplify() works here
        self.verify_simplify_topology(ts, [1, 2, 3])
        self.check_num_samples(
            ts,
            [(0, 5, 4), (0, 2, 1), (0, 7, 4), (0, 4, 2),
             (1, 4, 1), (1, 5, 3), (1, 8, 4), (1, 0, 0),
             (2, 5, 4), (2, 1, 1)])
        self.check_num_tracked_samples(
            ts, [1, 2, 5],
            [(0, 5, 3), (0, 2, 1), (0, 7, 3), (0, 4, 1),
             (1, 4, 1), (1, 5, 3), (1, 8, 3), (1, 0, 0),
             (2, 5, 3), (2, 1, 1)])
        self.check_sample_iterator(
            ts,
            [(0, 0, []), (0, 5, [5, 1, 2, 3]), (0, 4, [2, 3]),
             (1, 5, [5, 1, 2]), (2, 4, [2, 3])])
        # pedantically check the SparseTree methods on the second tree
        tst = ts.trees()
        t = next(tst)
        t = next(tst)
        self.assertEqual(t.branch_length(1), 0.4)
        self.assertEqual(t.is_internal(0), False)
        self.assertEqual(t.is_sample(0), True)
        self.assertEqual(t.is_internal(1), False)
        self.assertEqual(t.is_sample(1), True)
        self.assertEqual(t.is_internal(5), True)
        self.assertEqual(t.is_sample(5), False)
        self.assertEqual(t.is_internal(4), True)
        self.assertEqual(t.is_sample(4), False)
        self.assertEqual(t.root, 8)
        self.assertEqual(t.mrca(0, 1), 5)
        self.assertEqual(t.sample_size, 4)


class TestBadTrees(unittest.TestCase):
    """
    Tests for bad tree sequence topologies that can only be detected when we
    try to create trees.
    """

    def test_simplest_fully_overlapping_parent(self):
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           1
        3       0           2
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0.0     1.0     2       0
        0.0     1.0     2       1
        """)
        ts = msprime.load_text(nodes=nodes, edgesets=edgesets)
        self.assertRaises(_msprime.LibraryError, list, ts.trees())

    def test_simplest_paritially_overlapping_parent(self):
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           1
        3       0           2
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0.0     1.0     2       0
        0.5     1.0     2       1
        """)
        ts = msprime.load_text(nodes=nodes, edgesets=edgesets)
        self.assertRaises(_msprime.LibraryError, list, ts.trees())

    def test_simplest_contradictory_children(self):
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           1
        3       0           2
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0.0     1.0     2       0
        0.0     1.0     3       0
        """)
        ts = msprime.load_text(nodes=nodes, edgesets=edgesets)
        self.assertRaises(_msprime.LibraryError, list, ts.trees())

    def test_partial_overlap_contradictory_children(self):
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       0           1
        3       0           2
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0.0     1.0     2       0,1
        0.5     1.0     3       0
        """)
        ts = msprime.load_text(nodes=nodes, edgesets=edgesets)
        self.assertRaises(_msprime.LibraryError, list, ts.trees())


class TestPythonSimplifier(unittest.TestCase):
    """
    Tests that the test implementation of simplify() does what it's supposed to.
    """
    random_seed = 23
    #
    #          8
    #         / \
    #        /   \
    #       /     \
    #      7       \
    #     / \       6
    #    /   5     / \
    #   /   / \   /   \
    #  4   0   1 2     3
    small_tree_ex_nodes = """\
    id      is_sample   population      time
    0       1       0               0.00000000000000
    1       1       0               0.00000000000000
    2       1       0               0.00000000000000
    3       1       0               0.00000000000000
    4       1       0               0.00000000000000
    5       0       0               0.14567111023387
    6       0       0               0.21385545626353
    7       0       0               0.43508024345063
    8       0       0               1.60156352971203
    """
    small_tree_ex_edgesets = """\
    id      left            right           parent  children
    0       0.00000000      1.00000000      5       0,1
    1       0.00000000      1.00000000      6       2,3
    2       0.00000000      1.00000000      7       4,5
    3       0.00000000      1.00000000      8       6,7
    """

    def do_simplify(self, ts, samples=None, compare_lib=True):
        """
        Runs the Python test implementation of simplify.
        """
        if samples is None:
            samples = ts.samples()
        s = tests.Simplifier(ts, samples)
        new_ts = s.simplify()
        if compare_lib:
            lib_tables = ts.dump_tables()
            msprime.simplify_tables(
                samples=samples, nodes=lib_tables.nodes, edgesets=lib_tables.edgesets,
                sites=lib_tables.sites, mutations=lib_tables.mutations)
            py_tables = new_ts.dump_tables()
            self.assertEqual(lib_tables.nodes, py_tables.nodes)
            self.assertEqual(lib_tables.edgesets, py_tables.edgesets)
            self.assertEqual(lib_tables.migrations, py_tables.migrations)
            self.assertEqual(lib_tables.sites, py_tables.sites)
            self.assertEqual(lib_tables.mutations, py_tables.mutations)
        return new_ts

    def test_single_tree(self):
        ts = msprime.simulate(10, random_seed=self.random_seed)
        ts_single = single_childify(ts)
        tss = self.do_simplify(ts_single)
        self.assertEqual(list(tss.records()), list(ts.records()))

    def test_single_tree_mutations(self):
        ts = msprime.simulate(10, mutation_rate=1, random_seed=self.random_seed)
        self.assertGreater(ts.num_sites, 1)
        ts_single = single_childify(ts)
        tss = self.do_simplify(ts_single)
        self.assertEqual(list(tss.records()), list(ts.records()))
        self.assertEqual(list(tss.haplotypes()), list(ts.haplotypes()))

    def test_many_trees_mutations(self):
        ts = msprime.simulate(
            10, recombination_rate=1, mutation_rate=10, random_seed=self.random_seed)
        self.assertGreater(ts.num_trees, 2)
        self.assertGreater(ts.num_sites, 2)
        ts_single = single_childify(ts)
        tss = self.do_simplify(ts_single)
        self.assertEqual(list(tss.records()), list(ts.records()))
        self.assertEqual(list(tss.haplotypes()), list(ts.haplotypes()))

    def test_many_trees(self):
        ts = msprime.simulate(5, recombination_rate=4, random_seed=self.random_seed)
        self.assertGreater(ts.num_trees, 2)
        ts_single = single_childify(ts)
        tss = self.do_simplify(ts_single)
        self.assertEqual(list(tss.records()), list(ts.records()))

    def test_small_tree_internal_samples(self):
        ts = msprime.load_text(
            nodes=six.StringIO(self.small_tree_ex_nodes),
            edgesets=six.StringIO(self.small_tree_ex_edgesets))
        tables = ts.dump_tables()
        nodes = tables.nodes
        flags = nodes.flags
        # The parent of samples 0 and 1 is 5. Change this to an internal sample
        # and set 0 and 1 to be unsampled.
        flags[0] = 0
        flags[1] = 0
        flags[5] = msprime.NODE_IS_SAMPLE
        nodes.set_columns(flags=flags, time=nodes.time)
        ts = msprime.load_tables(nodes=nodes, edgesets=tables.edgesets)
        self.assertEqual(ts.sample_size, 4)
        tss = self.do_simplify(ts, [3, 5])
        self.assertEqual(tss.num_nodes, 3)
        self.assertEqual(tss.num_edgesets, 1)

    def test_small_tree_linear_samples(self):
        ts = msprime.load_text(
            nodes=six.StringIO(self.small_tree_ex_nodes),
            edgesets=six.StringIO(self.small_tree_ex_edgesets))
        tables = ts.dump_tables()
        nodes = tables.nodes
        flags = nodes.flags
        # 7 is above 0. These are the only two samples
        flags[:] = 0
        flags[0] = msprime.NODE_IS_SAMPLE
        flags[7] = msprime.NODE_IS_SAMPLE
        nodes.set_columns(flags=flags, time=nodes.time)
        ts = msprime.load_tables(nodes=nodes, edgesets=tables.edgesets)
        self.assertEqual(ts.sample_size, 2)
        tss = self.do_simplify(ts, [0, 7])
        self.assertEqual(tss.num_nodes, 2)
        self.assertEqual(tss.num_edgesets, 1)
        t = next(tss.trees())
        self.assertEqual(t.parent_dict, {0: 1})

    def test_small_tree_internal_and_external_samples(self):
        ts = msprime.load_text(
            nodes=six.StringIO(self.small_tree_ex_nodes),
            edgesets=six.StringIO(self.small_tree_ex_edgesets))
        tables = ts.dump_tables()
        nodes = tables.nodes
        flags = nodes.flags
        # 7 is above 0 and 1.
        flags[:] = 0
        flags[0] = msprime.NODE_IS_SAMPLE
        flags[1] = msprime.NODE_IS_SAMPLE
        flags[7] = msprime.NODE_IS_SAMPLE
        nodes.set_columns(flags=flags, time=nodes.time)
        ts = msprime.load_tables(nodes=nodes, edgesets=tables.edgesets)
        self.assertEqual(ts.sample_size, 3)
        tss = self.do_simplify(ts, [0, 1, 7])
        self.assertEqual(tss.num_nodes, 4)
        self.assertEqual(tss.num_edgesets, 2)
        t = next(tss.trees())
        self.assertEqual(t.parent_dict, {0: 3, 1: 3, 3: 2})

    def test_small_tree_mutations(self):
        ts = msprime.load_text(
            nodes=six.StringIO(self.small_tree_ex_nodes),
            edgesets=six.StringIO(self.small_tree_ex_edgesets))
        tables = ts.dump_tables()
        # Add some simple mutations here above the nodes we're keeping.
        tables.sites.add_row(position=0.25, ancestral_state="0")
        tables.sites.add_row(position=0.5, ancestral_state="0")
        tables.sites.add_row(position=0.75, ancestral_state="0")
        tables.sites.add_row(position=0.8, ancestral_state="0")
        tables.mutations.add_row(site=0, node=0, derived_state="1")
        tables.mutations.add_row(site=1, node=2, derived_state="1")
        tables.mutations.add_row(site=2, node=7, derived_state="1")
        tables.mutations.add_row(site=3, node=0, derived_state="1")
        ts = msprime.load_tables(
            nodes=tables.nodes, edgesets=tables.edgesets, sites=tables.sites,
            mutations=tables.mutations)
        self.assertEqual(ts.num_sites, 4)
        self.assertEqual(ts.num_mutations, 4)
        tss = self.do_simplify(ts, [0, 2])
        self.assertEqual(tss.sample_size, 2)
        self.assertEqual(tss.num_mutations, 4)
        self.assertEqual(list(tss.haplotypes()), ["1011", "0100"])

    def test_small_tree_fixed_sites(self):
        ts = msprime.load_text(
            nodes=six.StringIO(self.small_tree_ex_nodes),
            edgesets=six.StringIO(self.small_tree_ex_edgesets))
        tables = ts.dump_tables()
        # Add some simple mutations that will be fixed after simplify
        tables.sites.add_row(position=0.25, ancestral_state="0")
        tables.sites.add_row(position=0.5, ancestral_state="0")
        tables.sites.add_row(position=0.75, ancestral_state="0")
        tables.sites.add_row(position=0.8, ancestral_state="0")
        tables.mutations.add_row(site=0, node=7, derived_state="1")
        tables.mutations.add_row(site=1, node=2, derived_state="1")
        tables.mutations.add_row(site=2, node=3, derived_state="1")
        tables.mutations.add_row(site=3, node=6, derived_state="1")
        ts = msprime.load_tables(
            nodes=tables.nodes, edgesets=tables.edgesets, sites=tables.sites,
            mutations=tables.mutations)
        self.assertEqual(ts.num_sites, 4)
        self.assertEqual(ts.num_mutations, 4)
        tss = self.do_simplify(ts, [4, 1])
        self.assertEqual(tss.sample_size, 2)
        self.assertEqual(tss.num_mutations, 0)
        self.assertEqual(list(tss.haplotypes()), ["", ""])

    def test_small_tree_recurrent_mutations(self):
        ts = msprime.load_text(
            nodes=six.StringIO(self.small_tree_ex_nodes),
            edgesets=six.StringIO(self.small_tree_ex_edgesets))
        tables = ts.dump_tables()
        # Add recurrent mutation on the root branches
        tables.sites.add_row(position=0.25, ancestral_state="0")
        tables.mutations.add_row(site=0, node=6, derived_state="1")
        tables.mutations.add_row(site=0, node=7, derived_state="1")
        ts = msprime.load_tables(
            nodes=tables.nodes, edgesets=tables.edgesets, sites=tables.sites,
            mutations=tables.mutations)
        self.assertEqual(ts.num_sites, 1)
        self.assertEqual(ts.num_mutations, 2)
        tss = self.do_simplify(ts, [4, 3])
        self.assertEqual(tss.sample_size, 2)
        self.assertEqual(tss.num_sites, 1)
        self.assertEqual(tss.num_mutations, 2)
        self.assertEqual(list(tss.haplotypes()), ["1", "1"])

    def best_small_tree_back_mutations(self):
        ts = msprime.load_text(
            nodes=six.StringIO(self.small_tree_ex_nodes),
            edgesets=six.StringIO(self.small_tree_ex_edgesets))
        tables = ts.dump_tables()
        # Add a chain of mutations
        tables.sites.add_row(position=0.25, ancestral_state="0")
        tables.mutations.add_row(site=0, node=7, derived_state="1")
        tables.mutations.add_row(site=0, node=5, derived_state="0")
        tables.mutations.add_row(site=0, node=1, derived_state="1")
        ts = msprime.load_tables(
            nodes=tables.nodes, edgesets=tables.edgesets, sites=tables.sites,
            mutations=tables.mutations)
        self.assertEqual(ts.num_sites, 1)
        self.assertEqual(ts.num_mutations, 3)
        self.assertEqual(list(ts.haplotypes()), ["0", "1", "0", "0", "1"])
        # First check if we simplify for all samples and keep original state.
        tss = self.do_simplify(ts, [0, 1, 2, 3, 4])
        self.assertEqual(tss.sample_size, 5)
        self.assertEqual(tss.num_sites, 1)
        self.assertEqual(tss.num_mutations, 3)
        self.assertEqual(list(tss.haplotypes()), ["0", "1", "0", "0", "1"])

        # The ancestral state above 5 should be 0.
        tss = self.do_simplify(ts, [0, 1])
        self.assertEqual(tss.sample_size, 2)
        self.assertEqual(tss.num_sites, 1)
        self.assertEqual(tss.num_mutations, 1)
        self.assertEqual(list(tss.haplotypes()), ["0", "1"])

        # The ancestral state above 7 should be 1.
        tss = self.do_simplify(ts, [4, 0, 1])
        self.assertEqual(tss.sample_size, 3)
        self.assertEqual(tss.num_sites, 1)
        self.assertEqual(tss.num_mutations, 2)
        self.assertEqual(list(tss.haplotypes()), ["1", "0", "1"])

    def test_overlapping_unary_edgesets_internal_samples(self):
        nodes = six.StringIO("""\
        id      is_sample   time
        0       1           0
        1       1           0
        2       1           1
        """)
        edgesets = six.StringIO("""\
        left    right   parent  children
        0       2       2       0
        1       3       2       1
        """)
        ts = msprime.load_text(nodes, edgesets)
        tss = self.do_simplify(ts)
        self.assertEqual(tss.sample_size, 3)
        self.assertEqual(tss.num_trees, 3)
        trees = [{0: 2}, {0: 2, 1: 2}, {1: 2}]
        for t in tss.trees():
            self.assertEqual(t.parent_dict, trees[t.index])

    def test_internal_samples(self):
        nodes = six.StringIO("""\
        id      is_sample   population      time
        0       1       -1              1.00000000000000
        1       0       -1              1.00000000000000
        2       1       -1              1.00000000000000
        3       0       -1              1.31203521181726
        4       0       -1              2.26776380586006
        5       1       -1              0.00000000000000

        """)
        edgesets = six.StringIO("""\
        id      left            right           parent  children
        0       0.62185118      1.00000000      1       5
        1       0.00000000      0.62185118      2       5
        2       0.00000000      1.00000000      3       0,2
        3       0.00000000      1.00000000      4       1,3
        """)

        ts = msprime.load_text(nodes, edgesets)
        tss = self.do_simplify(ts, compare_lib=True)
        self.assertEqual(tss.sample_size, 3)
        self.assertEqual(tss.num_trees, 2)
        trees = [{0: 3, 1: 3, 2: 1}, {0: 3, 1: 3, 2: 4, 3: 4}]
        for t in tss.trees():
            self.assertEqual(t.parent_dict, trees[t.index])
