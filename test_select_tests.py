"""Quick-check test selection (tools/select_tests.py)."""
import tempfile
import unittest
from pathlib import Path

from tools.select_tests import CORE, select


class SelectTests(unittest.TestCase):
    def make_repo(self, files):
        folder = Path(tempfile.mkdtemp())
        for name, text in files.items():
            (folder / name).write_text(text, encoding='utf-8')
        return folder

    def test_core_always_and_importers_of_changed_modules(self):
        files = {name + '.py': '' for name in CORE}
        files.update({
            'test_alpha.py': 'import unittest\nfrom alpha import thing\n',
            'test_beta.py': 'import os, beta\n',
            'test_gamma.py': 'import alphabet\n',      # not "alpha"
        })
        root = self.make_repo(files)
        chosen = select(['alpha.py', 'beta.py', 'README.md'], root)
        self.assertEqual(chosen[:len(CORE)], list(CORE))
        self.assertIn('test_alpha', chosen)
        self.assertIn('test_beta', chosen)
        self.assertNotIn('test_gamma', chosen)

    def test_changed_test_files_run_once_and_subfolders_are_ignored(self):
        root = self.make_repo({'test_studio.py': '', 'test_new.py': 'from studio import x\n'})
        chosen = select(['test_new.py', 'test_new.py', 'tools/helper.py',
                         '.github/workflows/x.yml'], root)
        self.assertEqual(chosen.count('test_new'), 1)
        self.assertEqual(chosen, ['test_studio', 'test_new'])

    def test_hub_modules_do_not_pull_in_every_test(self):
        from tools.select_tests import HUB_LIMIT
        files = {f'test_w{i}.py': 'from hub import Window\n' for i in range(HUB_LIMIT + 1)}
        files['test_studio.py'] = 'from hub import Window\n'
        root = self.make_repo(files)
        self.assertEqual(select(['hub.py'], root), ['test_studio'])

    def test_shards_cover_every_module_once(self):
        from tools.select_tests import shard
        names = [f'test_{i}' for i in range(11)]
        parts = [shard(names, k, 4) for k in range(1, 5)]
        self.assertEqual(sorted(sum(parts, [])), sorted(names))
        self.assertTrue(all(parts))

    def test_this_repository_selects_real_modules(self):
        chosen = select(['workspace_layout.py'])
        self.assertIn('test_workspace_layout', chosen)
        for name in chosen:
            self.assertTrue(Path(name + '.py').exists(), name)


if __name__ == '__main__':
    unittest.main()
