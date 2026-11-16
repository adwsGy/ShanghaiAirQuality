"""Check live backend responses and the separately served frontend proxy."""
import argparse
import hashlib
import json
from pathlib import Path
import re

import httpx

ROOT = Path(__file__).resolve().parents[1]


def check(api_url, web_url):
    fixture = json.loads((ROOT / 'tests/fixtures/migration.json').read_text(encoding='utf-8'))
    with httpx.Client(timeout=20) as client:
        checked = 0
        for record in fixture['records']:
            url = api_url.rstrip('/') + '/api/v1/' + record['endpoint']
            response = client.get(url) if record['query'] is None else client.post(url, json=record['query'])
            response.raise_for_status()
            body = json.dumps(response.json(), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
            if hashlib.sha256(body.encode()).hexdigest() != record['response_sha256']:
                raise ValueError(f'Business response differs: {record["label"]}')
            checked += 1
        page = client.get(web_url)
        page.raise_for_status()
        if 'id="root"' not in page.text:
            raise ValueError('Frontend entry did not render its root element.')
        proxied = client.get(web_url.rstrip('/') + '/api/v1/metadata')
        proxied.raise_for_status()
        if proxied.json()['dataset_version'] != fixture['dataset_version']:
            raise ValueError('Frontend proxy does not use this dataset.')
        geometry = client.get(web_url.rstrip('/') + '/geometry/shanghai.geojson')
        geometry.raise_for_status()
        if geometry.json().get('type') != 'FeatureCollection':
            raise ValueError('Map asset is unavailable.')
        built_page = client.get(api_url)
        built_page.raise_for_status()
        assets = re.findall(r'(?:src|href)="(/assets/[^\"]+)"', built_page.text)
        if not assets:
            raise ValueError('Backend is not serving the built frontend.')
        for asset in assets:
            client.get(api_url.rstrip('/') + asset).raise_for_status()
    return {'dataset_version': fixture['dataset_version'], 'live_business_responses_checked': checked,
            'frontend_proxy': 'passed', 'map_asset': 'passed', 'built_frontend_assets': len(assets), 'model_calls_made': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-url', default='http://127.0.0.1:8000')
    parser.add_argument('--web-url', default='http://127.0.0.1:5173')
    args = parser.parse_args()
    print(json.dumps(check(args.api_url, args.web_url), indent=2))
