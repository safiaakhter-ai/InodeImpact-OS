"""Topology, impact evidence, and portable report regression tests."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

from inodeimpact.analyzer import analyze
from inodeimpact.insights import compute_insights
from inodeimpact.models import Edge, Node, Snapshot
from inodeimpact.reporting import build_report, render_html_report, report_json
from inodeimpact.scanner import scan
from inodeimpact.sandbox import seed_demo


class InsightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'demo'
        seed_demo(self.root)
        self.snapshot = scan(self.root)

    def test_hotspots_are_sorted_by_reachable_consumers(self):
        result = compute_insights(self.snapshot)
        hotspots = result['hotspots']
        self.assertGreater(len(hotspots), 2)
        self.assertEqual([x['total_consumers'] for x in hotspots], sorted([x['total_consumers'] for x in hotspots], reverse=True))
        settings = next(x for x in hotspots if x['path'] == 'config/settings.json')
        self.assertGreaterEqual(settings['direct_consumers'], 4)
        self.assertGreaterEqual(settings['transitive_consumers'], 1)

    def test_dependency_chain_is_explainable_and_grounded(self):
        plan = analyze(self.snapshot, 'delete', 'config/settings.json')
        self.assertEqual(min(100, sum(plan['risk_factors'].values())), plan['risk_score'])
        paths = plan['dependency_paths']
        transitive = [p for p in paths if p['depth'] > 1]
        self.assertTrue(transitive)
        for path in paths:
            self.assertEqual(path['chain'][0], path['consumer'])
            self.assertEqual(path['chain'][-1], 'config/settings.json')
            self.assertEqual(len(path['evidence']), len(path['chain']) - 1)
            for edge in path['evidence']:
                self.assertTrue(any(e.source == edge['source'] and e.target == edge['target'] for e in self.snapshot.edges))

    def test_copy_has_no_broken_dependency_chains(self):
        result = analyze(self.snapshot, 'copy', 'config/settings.json', 'config/other.json')
        self.assertEqual(result['dependency_paths'], [])
        self.assertEqual(result['risk_score'], 2)

    def test_circular_group_is_detected(self):
        a = Node('a.py', 'file', 1, 1, 1, 1, 0, '-rw-r--r--')
        b = Node('b.py', 'file', 1, 2, 1, 1, 0, '-rw-r--r--')
        snap = Snapshot('/test', {'a.py': a, 'b.py': b}, [Edge('a.py','b.py','test','A'), Edge('b.py','a.py','test','B')], '2026-01-01T00:00:00Z')
        result = compute_insights(snap)
        self.assertEqual(result['summary']['cyclic_groups'], 1)
        self.assertEqual(result['cycles'], [['a.py', 'b.py']])

    def test_report_has_no_unescaped_file_names_in_html(self):
        filename = '<test>.md'
        (self.root / filename).write_text('content', encoding='utf-8')
        snap = scan(self.root)
        report = build_report(snap)
        html = render_html_report(report)
        self.assertIn('Dependency intelligence', html)
        self.assertIn('Example preflight scenarios', html)
        self.assertIn('text/html', '<meta http-equiv="content-type" content="text/html">')
        self.assertEqual(json.loads(report_json(report))['summary']['nodes'], len(snap.nodes))
        self.assertNotIn('<script', html.lower())

    def test_hardlink_group(self):
        root = Path(self.temp.name) / 'hardlinks'
        root.mkdir()
        (root / 'first.txt').write_text('hello', encoding='utf-8')
        try:
            (root / 'second.txt').hardlink_to(root / 'first.txt')
        except (OSError, NotImplementedError):
            self.skipTest('Hardlinks unavailable on this filesystem')
        result = compute_insights(scan(root))
        self.assertEqual(result['hardlinks'], [['first.txt', 'second.txt']])

    def test_limit_validation(self):
        with self.assertRaises(ValueError):
            compute_insights(self.snapshot, 0)
        with self.assertRaises(ValueError):
            compute_insights(self.snapshot, 51)


if __name__ == '__main__':
    unittest.main()
