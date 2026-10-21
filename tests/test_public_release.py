import importlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import yaml
from fastapi import HTTPException
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]


class PublicReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config_path = ROOT / 'config' / 'config.yaml'
        cls.created_config = not cls.config_path.exists()
        if cls.created_config:
            cls.config_path.write_text((ROOT / 'config' / 'config.example.yaml').read_text())
        cls.web = importlib.import_module('extract.web_app')

    @classmethod
    def tearDownClass(cls):
        if cls.created_config:
            cls.config_path.unlink()

    def test_config_cannot_be_read_or_written(self):
        for writable in (False, True):
            with self.assertRaises(HTTPException) as error:
                self.web.validate_document_path(self.config_path, writable=writable)
            self.assertEqual(error.exception.status_code, 403)

    def test_source_and_parent_traversal_are_denied(self):
        for path in (ROOT / 'main.py', ROOT.parent / 'private.txt'):
            with self.assertRaises(HTTPException):
                self.web.validate_document_path(path)

    def test_symlink_cannot_escape_document_root(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'results') as tmp:
            link = Path(tmp) / 'config-link.yaml'
            link.symlink_to(self.config_path)
            with self.assertRaises(HTTPException):
                self.web.validate_document_path(link.resolve())

    def test_document_round_trip(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'results') as tmp:
            target = Path(tmp) / 'result.json'
            relative = str(target.relative_to(ROOT))
            with TestClient(self.web.app) as client:
                response = client.post('/api/save', json={'path': relative, 'content': {'status': 'review'}})
                self.assertEqual(response.status_code, 200)
                response = client.post('/api/preview', json={'path': relative})
                self.assertEqual(response.json(), {'status': 'review'})
                self.assertEqual(client.get('/api/download', params={'path': 'config/config.yaml'}).status_code, 403)

    def test_password_special_characters_are_not_in_logs(self):
        from extract.PG_select import load_db_url, mask_password_in_url
        with tempfile.TemporaryDirectory() as tmp:
            config = yaml.safe_load((ROOT / 'config/config.example.yaml').read_text())
            config['database']['password'] = 'test@only:/?%value'
            path = Path(tmp) / 'config.yaml'
            path.write_text(yaml.safe_dump(config))
            url = load_db_url(path)
            self.assertEqual(url.password, config['database']['password'])
            self.assertNotIn(config['database']['password'], mask_password_in_url(url))

    def test_json_repair_and_expected_types(self):
        from core.llm_handler import LLMHandler
        handler = object.__new__(LLMHandler)
        self.assertEqual(handler._robust_json_parse('```json\n{"a": 1,}\n```', dict), {'a': 1})
        self.assertEqual(handler._robust_json_parse('{"a": 1}', list), [{'a': 1}])

    def test_api_starts_without_external_calls(self):
        import main
        with patch.object(main.llm, 'chat_completion_json', side_effect=AssertionError('unexpected model call')):
            with TestClient(main.app) as client:
                self.assertEqual(client.get('/openapi.json').status_code, 200)
                self.assertEqual(client.post('/full_pipeline', json={}).status_code, 422)


if __name__ == '__main__':
    unittest.main()
