"""Full-response parity with the source application, without source imports."""
import hashlib
import json
from pathlib import Path
import unittest

from fastapi.testclient import TestClient
from api.app import create_app


class MigrationTests(unittest.TestCase):
    def test_business_responses_match_the_source_application(self):
        fixture = json.loads((Path(__file__).parent / 'fixtures/migration.json').read_text(encoding='utf-8'))
        with TestClient(create_app()) as client:
            for record in fixture['records']:
                with self.subTest(record['label']):
                    path = '/api/v1/' + record['endpoint']
                    response = client.get(path) if record['query'] is None else client.post(path, json=record['query'])
                    self.assertEqual(response.status_code, 200, response.text)
                    canonical = json.dumps(response.json(), ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)
                    self.assertEqual(hashlib.sha256(canonical.encode()).hexdigest(), record['response_sha256'])
            self.assertEqual(client.get('/ai-experiment').status_code, 404)
            self.assertEqual(client.get('/api/v1/ai/cases').status_code, 404)


if __name__ == '__main__':
    unittest.main()
