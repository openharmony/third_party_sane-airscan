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
import fcntl
import hashlib
import json
import argparse
import os
import subprocess
import sys
import shutil
import tempfile
from pathlib import Path


def _relative_depfile_inputs(paths):
    result = []
    for path in paths:
        try:
            result.append(os.path.relpath(path))
        except ValueError:
            result.append(path)  # Different Windows drives cannot be rebased.
    return sorted(result)


def file_digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def replace_file(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix='.airscan-file-')
    os.close(descriptor)
    try:
        shutil.copy2(source, temporary)
        os.replace(temporary, destination)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def recover_transaction(source, journal):
    if not journal.exists():
        return
    entries = json.loads((journal / 'state.json').read_text())
    for relative, state in entries.items():
        target = source / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts:
            raise RuntimeError('Invalid airscan transaction path')
        if target.is_symlink() or source.resolve() not in (target.resolve(), *target.resolve().parents):
            raise RuntimeError('Airscan transaction target escapes source tree')
        if file_digest(target) not in (state['old'], state['new']):
            raise RuntimeError(f'Airscan recovery would overwrite an external edit: {target}')
    for relative, state in entries.items():
        target = source / relative
        if state['old'] is None:
            if target.exists():
                target.unlink()
        elif file_digest(target) != state['old']:
            replace_file(journal / 'original' / relative, target)
    shutil.rmtree(journal)


def commit_patch_files(source, shadow, paths):
    changed = [relative for relative in sorted(paths)
               if file_digest(source / relative) != file_digest(shadow / relative)]
    if not changed:
        return
    journal = source / '.airscan-patch-transaction'
    with tempfile.TemporaryDirectory(dir=source, prefix='.airscan-prepare-') as temporary:
        prepared = Path(temporary) / 'journal'
        prepared.mkdir()
        entries = {}
        for relative in changed:
            original, patched = source / relative, shadow / relative
            if original.is_symlink() or source.resolve() not in (original.resolve(), *original.resolve().parents):
                raise RuntimeError(f'Airscan patch target escapes source tree: {original}')
            entries[relative] = {'old': file_digest(original), 'new': file_digest(patched)}
            if original.is_file():
                backup = prepared / 'original' / relative
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, backup)
        (prepared / 'state.json').write_text(json.dumps(entries), encoding='utf-8')
        os.replace(prepared, journal)
        try:
            for relative in changed:
                patched, original = shadow / relative, source / relative
                if patched.is_file():
                    replace_file(patched, original)
                elif original.exists():
                    original.unlink()
        except BaseException:
            # If rollback also fails, keep the journal for the next invocation.
            recover_transaction(source, journal)
            raise
        shutil.rmtree(journal)


def apply_patch(source_dir):
    source = Path(source_dir).absolute()
    # Keep one lock inode per source tree. Do not unlink it after unlocking:
    # waiters must not end up locking different inodes. An ordinary writable
    # file also supports NFS exclusive flock, unlike a read-only directory FD.
    descriptor = os.open(source / ".airscan-patch.lock",
                         os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o666)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        recover_transaction(source, source / '.airscan-patch-transaction')
        return _apply_patch_locked(str(source))
    finally:
        os.close(descriptor)


def _apply_patch_locked(source_dir):

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
        # -N also applies to -R: reject an unreversed patch instead of letting
        # --batch silently ignore -R and apply it forwards during rollback.
        command = ['patch', '--batch', '--forward', '-p1', '--fuzz=0', '--no-backup-if-mismatch',
                   '-i', str(Path(source_dir) / 'patches' / name), '-d', str(directory)]
        if reverse:
            command.append('--reverse')
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
            commit_patch_files(Path(source_dir), shadow, paths)
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
        write_depfile(args.depfile, args.stamp,
                      _relative_depfile_inputs(dependencies), add_pydeps=False)
    if args.stamp:
        Path(args.stamp).parent.mkdir(parents=True, exist_ok=True)
        Path(args.stamp).touch()
    return 0


if __name__ == '__main__':
    sys.exit(main())
