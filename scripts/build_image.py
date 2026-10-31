#!/usr/bin/env python3
"""Build with honest source provenance; requires only Python's standard library."""
import hashlib
import pathlib
import subprocess

root = pathlib.Path(__file__).resolve().parents[1]


def git(*args):
    return subprocess.run(['git', *args], cwd=root, capture_output=True, text=True)


def main():
    revision = git('rev-parse', '--verify', 'HEAD')
    status = git('status', '--porcelain')
    digest = hashlib.sha256()
    paths = [root / p for p in ['Dockerfile', 'requirements.txt', '.dockerignore',
                               'LICENSE', 'NOTICE', 'THIRD_PARTY_NOTICES.md']]
    for directory in ['src', 'docker', 'scripts', '.github']:
        paths.extend((root / directory).rglob('*'))
    for path in sorted(paths):
        if path.is_file() and not any(p in ('__pycache__', '.pytest_cache') or p.endswith('.egg-info') for p in path.parts):
            digest.update(str(path.relative_to(root)).encode() + b'\0' + path.read_bytes())
    command = ['docker', 'build', '--progress=plain', '-t', 'robot-reliability:jazzy',
        '--build-arg', 'GIT_REVISION=' + (revision.stdout.strip() if revision.returncode == 0 else 'unborn'),
        '--build-arg', 'GIT_DIRTY=' + (str(bool(status.stdout)).lower() if status.returncode == 0 else 'unknown'),
        '--build-arg', 'SOURCE_SHA256=' + digest.hexdigest(), '.']
    raise SystemExit(subprocess.call(command, cwd=root))


if __name__ == '__main__':
    main()
