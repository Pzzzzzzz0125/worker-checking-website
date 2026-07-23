import unittest
from unittest.mock import patch

from api import _lark


class LarkAPITests(unittest.TestCase):
    def test_paged_items_uses_requested_page_size(self):
        calls = []

        def api(method, path, *, token, body=None, query=None):
            del method, path, token, body
            calls.append(dict(query or {}))
            if len(calls) == 1:
                return {
                    "data": {
                        "items": [{"id": "one"}],
                        "has_more": True,
                        "page_token": "next",
                    }
                }
            return {"data": {"items": [{"id": "two"}], "has_more": False}}

        with patch.object(_lark, "lark_api", side_effect=api):
            result = _lark.paged_items("/items", token="token", page_size=500)

        self.assertEqual(result, [{"id": "one"}, {"id": "two"}])
        self.assertEqual(calls[0]["page_size"], 500)
        self.assertEqual(calls[1]["page_token"], "next")

    def test_paged_items_keeps_filters_across_pages(self):
        calls = []

        def api(method, path, *, token, body=None, query=None):
            del method, path, token, body
            calls.append(dict(query or {}))
            if len(calls) == 1:
                return {"data": {"items": [], "has_more": True, "page_token": "next"}}
            return {"data": {"items": [], "has_more": False}}

        with patch.object(_lark, "lark_api", side_effect=api):
            _lark.paged_items(
                "/items", token="token", page_size=500,
                query={"filter": "CurrentValue.[Worker Key]=\"7\""},
            )

        self.assertEqual(calls[0]["filter"], calls[1]["filter"])
        self.assertEqual(calls[1]["page_token"], "next")


if __name__ == "__main__":
    unittest.main()
