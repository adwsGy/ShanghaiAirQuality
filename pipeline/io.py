"""Local dataset files shared by the cleaning and rebuilding commands."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data/processed'


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def write_csv(frame, path):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    compressed = path.name.endswith('.gz')
    frame.to_csv(path, index=False, encoding='utf-8' if compressed else 'utf-8-sig',
                 float_format='%.15g', compression={'method': 'gzip', 'mtime': 0} if compressed else None)


def write_json(value, path):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')


def manifest(directory=DATA):
    directory = Path(directory)
    value = json.loads((directory / 'data_manifest.json').read_text(encoding='utf-8'))
    status = json.loads((directory / 'build_status.json').read_text(encoding='utf-8'))
    if status.get('status') != 'complete' or status.get('dataset_version') != value['dataset_version']:
        raise ValueError('Dataset is incomplete or its version does not match build_status.json.')
    return value


def checked_path(directory, name):
    root = Path(directory).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or path == root:
        raise ValueError(f'Invalid dataset file path: {name}')
    return path
