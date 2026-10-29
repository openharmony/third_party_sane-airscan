#!/usr/bin/env python
# -*- coding: utf-8 -*-
# Copyright (c) 2025 Huawei Device Co., Ltd.
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

import tarfile
import argparse
import os
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path


def apply_patch(source_dir):
    patch_list = [
        'oh-transplant.patch',
        'oh-fix-subtraction-underflow.patch',
        'oh-fix-heap-overflow-dimension.patch',
        'oh-fix-resolution-overflow.patch',
        'oh-fix-http-hdr-params-parse-null-deref.patch',
        'oh-fix-http-body-limit.patch',
        'oh-fix-empty-source-caps.patch',
        'oh-fix-eloop-uv-run-mutex-serialization.patch',
    ]

    # Verify and transform a private copy first. This accepts both pristine and
    # already-patched trees, never reruns failed patches into the source tree.
    paths = set()
    for patch in patch_list:
        for line in (Path(source_dir) / 'patches' / patch).read_text().splitlines():
            if line.startswith(('--- a/', '+++ b/')):
                relative = line[6:].split('\t')[0]
                if Path(relative).is_absolute() or '..' in Path(relative).parts:
                    raise ValueError(relative)
                paths.add(relative)

    def execute_patch(directory, name, reverse=False):
        command = ['patch', '--batch', '-p1', '--fuzz=0', '--no-backup-if-mismatch',
                   '-i', str(Path(source_dir) / 'patches' / name), '-d', str(directory)]
        command.append('--reverse' if reverse else '--forward')
        return subprocess.run(command, text=True, stdout=subprocess.PIPE,
                              stderr=subprocess.STDOUT)

    # A prefix may already be applied from an earlier build. Reverse it in a
    # disposable tree, then apply the complete patch series in order.
    for prefix in range(len(patch_list), -1, -1):
        with tempfile.TemporaryDirectory(prefix='airscan-patches-') as temporary:
            shadow = Path(temporary)
            for relative in paths:
                original = Path(source_dir) / relative
                if original.is_file():
                    (shadow / relative).parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(original, shadow / relative)
            if any(execute_patch(shadow, name, True).returncode
                   for name in reversed(patch_list[:prefix])):
                continue
            for name in patch_list:
                result = execute_patch(shadow, name)
                if result.returncode:
                    raise RuntimeError(f'{name} failed:\n{result.stdout}')
            for relative in paths:
                original, patched = Path(source_dir) / relative, shadow / relative
                if patched.is_file() and (not original.exists() or original.read_bytes() != patched.read_bytes()):
                    shutil.copyfile(patched, original)
            return sorted(str(Path(source_dir) / relative) for relative in paths)
    raise RuntimeError('Cannot determine sane-airscan patch state')


def main():
    backends_path = argparse.ArgumentParser()
    backends_path.add_argument('--source-dir', help='generate path of log', required=True)
    backends_path.add_argument('--stamp')
    backends_path.add_argument('--depfile')
    args = backends_path.parse_args()
    source_dir = os.path.abspath(args.source_dir)
    dependencies = apply_patch(source_dir)
    if args.depfile:
        sys.path.insert(0, str(Path(source_dir).parents[1] / 'build'))
        from scripts.util.build_utils import write_depfile
        write_depfile(args.depfile, args.stamp, dependencies, add_pydeps=False)
    if args.stamp:
        Path(args.stamp).parent.mkdir(parents=True, exist_ok=True)
        Path(args.stamp).touch()
    return 0


if __name__ == '__main__':
    sys.exit(main())