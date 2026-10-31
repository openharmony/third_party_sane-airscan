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
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

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


if __name__ == '__main__':
    unittest.main(verbosity=2)
