import unittest
from unittest.mock import patch, Mock
import scraper

class ScraperTests(unittest.TestCase):
    def test_invalid_code(self):
        self.assertEqual(scraper.sanitize_code("NEW CODE"), "")
        self.assertEqual(scraper.sanitize_code(" Abc123 "), "Abc123")
    def test_open_api(self):
        response = Mock()
        response.json.return_value = [{"code":"TEST123","rewards":["50 coins"]}]
        with patch.object(scraper, "get_with_retry", return_value=response):
            self.assertEqual(scraper.fetch_open_codes({"open_slug":"nte"}), [("TEST123","• 50 coins",None)])
    def test_invalid_api(self):
        response = Mock()
        response.json.return_value = {"error":"bad"}
        with patch.object(scraper, "get_with_retry", return_value=response):
            self.assertIsNone(scraper.fetch_open_codes({"open_slug":"wuwa"}))
    def test_discord_rejection(self):
        response = Mock(status_code=400)
        with patch.object(scraper.requests, "post", return_value=response):
            with self.assertRaises(RuntimeError):
                scraper.post_webhook({})
