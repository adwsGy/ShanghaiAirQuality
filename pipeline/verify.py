"""Verify the included dataset without raw archives, saved sessions or a model."""
import argparse
import json
from pathlib import Path

from pipeline.io import DATA, checked_path, manifest, sha256


def verify(directory=DATA):
    directory = Path(directory)
    info = manifest(directory)
    for name, record in info['outputs'].items():
        path = checked_path(directory, name)
        if not path.is_file() or sha256(path) != record['sha256']:
            raise ValueError(f'Dataset checksum mismatch: {name}')
        if path.stat().st_size != record['bytes']:
            raise ValueError(f'Dataset size mismatch: {name}')
    return {'dataset_version': info['dataset_version'], 'files_verified': len(info['outputs']),
            'policy_id': info['statistics_update']['policy_id'], 'model_calls_made': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=DATA)
    args = parser.parse_args()
    print(json.dumps(verify(args.directory), indent=2))
