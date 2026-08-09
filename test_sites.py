import unittest
from pathlib import Path

from report_handlers.sites import import_sites, parse_site_file, split_address


class FakeBase:
    def __init__(self):
        self.rows = {}

    def table_ids(self):
        return {"Sites": "Sites"}

    def records(self, table_name, **kwargs):
        return [
            {"record_id": key, "fields": dict(fields)}
            for key, fields in self.rows.items()
        ]

    def batch_set_by_key(self, table_name, key_field, rows, **kwargs):
        for row in rows:
            self.rows[row[key_field]] = dict(row)
        return {"created": len(rows), "updated": 0}


class SiteLibraryTests(unittest.TestCase):
    def test_supplied_workbook_parses_and_deduplicates(self):
        path = Path("/Users/jianfuzhao/Desktop/Address(1).xlsx")
        if not path.exists():
            self.skipTest("User-supplied address workbook is not available")
        parsed = parse_site_file(path.read_bytes(), path.name)
        self.assertEqual(len(parsed), 70)
        base = FakeBase()
        result = import_sites(base, parsed, source=path.name)
        self.assertEqual(result["created"], 68)
        self.assertEqual(result["duplicates_skipped"], 2)
        self.assertEqual(result["active"], 68)

    def test_address_components_are_preserved_without_guessing(self):
        complete = split_address("444 Pocatello Dr, San Jose, CA 95111")
        self.assertEqual(complete, {
            "address_line_1": "444 Pocatello Dr",
            "city": "San Jose",
            "state": "CA",
            "zip_code": "95111",
        })
        partial = split_address("1529 Pacific Ave, Alameda")
        self.assertEqual(partial["city"], "Alameda")
        self.assertEqual(partial["state"], "")
        self.assertEqual(partial["zip_code"], "")

    def test_replace_archives_sites_omitted_from_new_library(self):
        base = FakeBase()
        import_sites(base, [
            {"full_address": "100 Main St, San Jose, CA 95112"},
            {"full_address": "200 Oak St, San Jose, CA 95112"},
        ], source="first.xlsx")
        result = import_sites(
            base,
            [{"full_address": "100 Main St, San Jose, CA 95112"}],
            source="replacement.xlsx",
            replace=True,
        )
        self.assertEqual(result["archived"], 1)
        self.assertEqual(result["active"], 1)


if __name__ == "__main__":
    unittest.main()
