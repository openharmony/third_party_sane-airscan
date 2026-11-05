#!/usr/bin/env python3
# Copyright (c) 2026 Huawei Device Co., Ltd.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Exercise the real series starting from Git contents, not a built source tree."""
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SERIES = (
    'oh-transplant.patch',
    'oh-fix-subtraction-underflow.patch',
    'oh-fix-heap-overflow-dimension.patch',
    'oh-fix-resolution-overflow.patch',
    'oh-fix-http-hdr-params-parse-null-deref.patch',
    'oh-fix-http-body-limit.patch',
    'oh-fix-empty-source-caps.patch',
    'oh-fix-eloop-uv-run-mutex-serialization.patch',
)
SPEC = importlib.util.spec_from_file_location('airscan_patch_install', ROOT / 'patch_install.py')
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def source_state(root):
    return {p.name: (p.read_bytes(), p.stat().st_mtime_ns)
            for p in root.iterdir() if p.suffix in ('.c', '.h')}


def tracked_source(root):
    paths = subprocess.check_output(
        ['git', '-C', str(ROOT), 'ls-tree', '-r', '--name-only', 'HEAD'], text=True)
    for name in paths.splitlines():
        if not (name.endswith(('.c', '.h')) or name.startswith('patches/')):
            continue
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(subprocess.check_output(
            ['git', '-C', str(ROOT), 'show', 'HEAD:' + name]))


def apply_forward(root, name):
    subprocess.run(
        ['patch', '--batch', '--forward', '--fuzz=0', '-p1',
         '-i', str(root / 'patches' / name), '-d', str(root)],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)


class PatchInstallTest(unittest.TestCase):
    def test_every_series_prefix_from_clean_git_and_repeat(self):
        with tempfile.TemporaryDirectory(prefix='airscan-clean-git-') as temporary:
            base = Path(temporary)
            pristine = base / 'pristine'
            pristine.mkdir()
            tracked_source(pristine)
            golden = base / 'golden'
            shutil.copytree(pristine, golden)
            for name in SERIES:
                apply_forward(golden, name)
            expected = {name: state[0] for name, state in source_state(golden).items()}
            for prefix in range(len(SERIES) + 1):
                with self.subTest(prefix=prefix):
                    case = base / ('prefix-' + str(prefix))
                    shutil.copytree(pristine, case)
                    for name in SERIES[:prefix]:
                        apply_forward(case, name)
                    MODULE.apply_patch(str(case))
                    self.assertEqual(expected, {
                        name: state[0] for name, state in source_state(case).items()})
                    before = source_state(case)
                    MODULE.apply_patch(str(case))
                    self.assertEqual(before, source_state(case))
                    self.assertFalse(list(case.rglob('*.rej')))

    def test_late_patch_failure_does_not_change_clean_git_sources(self):
        with tempfile.TemporaryDirectory(prefix='airscan-invalid-series-') as temporary:
            root = Path(temporary)
            tracked_source(root)
            (root / 'patches' / SERIES[-1]).write_text('not a patch\n')
            before = source_state(root)
            with self.assertRaises(RuntimeError):
                MODULE.apply_patch(str(root))
            self.assertEqual(before, source_state(root))
            self.assertFalse(list(root.rglob('*.rej')))


class RelativeDepfileTest(unittest.TestCase):
    def test_conversion_preserves_lexical_paths_and_spaces(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source with space.h'
            source.write_text('header')
            alias = root / 'alias.h'
            alias.symlink_to(source.name)
            self.assertEqual(MODULE._relative_depfile_inputs([str(source), str(alias)]),
                             sorted([os.path.relpath(source), os.path.relpath(alias)]))

    def test_different_drive_keeps_original_path(self):
        with mock.patch.object(MODULE.os.path, 'relpath', side_effect=ValueError('different drive')):
            self.assertEqual(MODULE._relative_depfile_inputs(['/external/input.h']),
                             ['/external/input.h'])


class NinjaDepfileTest(unittest.TestCase):
    def setUp(self):
        project = ROOT.parents[1]
        self.gn = project / 'prebuilts/build-tools/linux-x86/bin/gn'
        self.ninja = project / 'prebuilts/build-tools/linux-x86/bin/ninja'
        if not self.gn.is_file() or not self.ninja.is_file():
            self.skipTest('workspace GN and Ninja prebuilts are required')
        self.temporary = tempfile.TemporaryDirectory(prefix='airscan-relative-depfile-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / 'workspace'
        self.source = self.root / 'third_party/sane-airscan'
        self.source.mkdir(parents=True)
        tracked_source(self.source)
        shutil.copy2(ROOT / 'patch_install.py', self.source / 'patch_install.py')
        (self.root / 'build').symlink_to(project / 'build', target_is_directory=True)
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1')
        self.ninja_prefix = []
        (self.root / '.gn').write_text('buildconfig = "//BUILDCONFIG.gn"\n'
                                      'script_executable = ' + json.dumps(sys.executable) + '\n')
        (self.root / 'BUILDCONFIG.gn').write_text('set_default_toolchain("//:host")\n')
        (self.root / 'BUILD.gn').write_text('''toolchain("host") {
  tool("stamp") { command = "touch {{output}}" }
  tool("action") { }
}
group("default") { deps = [ "//third_party/sane-airscan:airscan_action" ] }
''')
        gn_source = (ROOT / 'BUILD.gn').read_text()
        start = gn_source.index('action("airscan_action") {')
        end = gn_source.index('{', start)
        depth = 1
        while depth:
            end += 1
            depth += (gn_source[end] == '{') - (gn_source[end] == '}')
        (self.source / 'BUILD.gn').write_text('source_dir = "//third_party/sane-airscan"\n'
                                             + gn_source[start:end + 1] + '\n')
        self.command([self.gn, 'gen', 'out/probe'])
        description = json.loads(self.command([
            self.gn, 'desc', 'out/probe', '//third_party/sane-airscan:airscan_action', '--format=json']))
        args = next(iter(description.values()))['args']
        self.stamp_name = args[args.index('--stamp') + 1]
        self.depfile_name = args[args.index('--depfile') + 1]

    def command(self, arguments, expected=0):
        if arguments[0] == self.ninja:
            arguments = self.ninja_prefix + arguments
        result = subprocess.run([str(value) for value in arguments], cwd=self.root,
                                env=self.env, text=True, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT)
        self.assertEqual(result.returncode, expected, result.stdout)
        return result.stdout

    def build(self, expected=0):
        return self.command([self.ninja, '-C', 'out/probe', 'airscan_action'], expected)

    def stamp(self):
        return self.root / 'out/probe' / self.stamp_name

    def depfile(self):
        return self.root / 'out/probe' / self.depfile_name

    def assert_no_work(self):
        self.assertIn('no work to do', self.build())

    def edit_header(self):
        header = self.source / 'airscan.h'
        header.write_bytes(header.read_bytes() + b'\n/* Incremental input edit. */\n')
        expected = header.read_bytes()
        self.assertNotIn('no work to do', self.build())
        self.assertEqual(header.read_bytes(), expected)
        self.assert_no_work()

    def test_clean_payload_relative_dependencies_and_noop(self):
        golden = Path(self.temporary.name) / 'golden'
        shutil.copytree(self.source, golden)
        for name in SERIES:
            apply_forward(golden, name)
        expected = {name: record[0] for name, record in source_state(golden).items()}
        self.build()
        self.assertEqual(expected, {name: record[0] for name, record in source_state(self.source).items()})
        target, dependencies = self.depfile().read_text().split(': ', 1)
        self.assertEqual(target, self.stamp_name)
        dependencies = shlex.split(dependencies)
        self.assertTrue(dependencies)
        self.assertTrue(all(not os.path.isabs(path) for path in dependencies))
        self.assertIn(os.path.relpath(self.source / 'airscan.h', self.root / 'out/probe'), dependencies)
        before = source_state(self.source)
        self.assert_no_work()
        self.assertEqual(before, source_state(self.source))

    def test_real_header_edit_rebuilds_once(self):
        self.build()
        self.edit_header()

    def test_patch_timestamp_change_keeps_payloads_and_converges(self):
        self.build()
        before = source_state(self.source)
        patch = self.source / 'patches' / SERIES[0]
        patch.write_bytes(patch.read_bytes())
        self.assertNotIn('no work to do', self.build())
        self.assertEqual(before, source_state(self.source))
        self.assert_no_work()

    def test_missing_output_is_repaired(self):
        self.build()
        before = source_state(self.source)
        self.stamp().unlink()
        self.assertNotIn('no work to do', self.build())
        self.assertTrue(self.stamp().is_file())
        self.assertEqual(before, source_state(self.source))
        self.assert_no_work()

    def test_failure_does_not_refresh_success_and_retry_recovers(self):
        self.build()
        before = source_state(self.source)
        success = (self.stamp().stat().st_mtime_ns, self.depfile().read_bytes(),
                   self.depfile().stat().st_mtime_ns)
        patch = self.source / 'patches' / SERIES[-1]
        valid = patch.read_bytes()
        patch.write_text('not a patch\n')
        self.build(expected=1)
        self.build(expected=1)
        self.assertEqual(before, source_state(self.source))
        self.assertEqual(success, (self.stamp().stat().st_mtime_ns, self.depfile().read_bytes(),
                                   self.depfile().stat().st_mtime_ns))
        patch.write_bytes(valid)
        self.build()
        self.assert_no_work()

    def relocate(self):
        canonical = self.root
        moved = self.root.with_name('renamed-workspace')
        self.root.rename(moved)
        self.root = moved
        self.source = moved / 'third_party/sane-airscan'
        return canonical

    def test_relative_action_after_direct_directory_rename(self):
        self.build()
        self.relocate()
        self.assert_no_work()
        self.edit_header()

    def test_private_mapping_after_directory_rename(self):
        bwrap = shutil.which('bwrap')
        if not bwrap:
            self.skipTest('bubblewrap is required for canonical mapping')
        self.build()
        canonical = self.relocate()
        path = ROOT.parents[1] / 'build/scripts/incremental_workspace.py'
        spec = importlib.util.spec_from_file_location('airscan_incremental_workspace', path)
        workspace = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(workspace)
        self.ninja_prefix = [bwrap, '--die-with-parent', '--bind', '/', '/',
                             *workspace.private_mountpoint(canonical),
                             '--proc', '/proc', '--dev-bind', '/dev', '/dev',
                             '--bind', str(self.root), str(canonical), '--chdir', str(canonical), '--']
        self.assert_no_work()
        self.edit_header()
        self.assertFalse(canonical.exists())


if __name__ == '__main__':
    unittest.main(verbosity=2)
