import unittest
from pathlib import Path

from report_handlers.sites import SiteResolver, import_sites, parse_site_file, split_address


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
    def test_legacy_labels_resolve_by_address_prefix_number_and_equals_marker(self):
        resolver = SiteResolver([
            {
                "site_key": "woodland", "name": "1049 Woodland Ave, Menlo Park, CA 94025",
                "full_address": "1049 Woodland Ave, Menlo Park, CA 94025",
                "address_line_1": "1049 Woodland Ave", "aliases": "", "active": True,
                "verified": True,
            },
            {
                "site_key": "crosswind", "name": "1073 Crosswind Ct, San Jose, CA 95120",
                "full_address": "1073 Crosswind Ct, San Jose, CA 95120",
                "address_line_1": "1073 Crosswind Ct", "aliases": "", "active": True,
                "verified": True,
            },
        ])
        self.assertEqual(
            resolver.resolve("1049 Woodland")["name"],
            "1049 Woodland Ave, Menlo Park, CA 94025",
        )
        with_equals = resolver.resolve("1073 Crosswind =")
        self.assertTrue(with_equals["matched"])
        self.assertTrue(with_equals["has_equals"])
        self.assertEqual(with_equals["site_key"], "crosswind")

    def test_ambiguous_street_number_is_kept_for_manual_review(self):
        resolver = SiteResolver([
            {
                "site_key": "gridley", "name": "444 Gridley St, San Jose, CA 95127",
                "full_address": "444 Gridley St, San Jose, CA 95127",
                "address_line_1": "444 Gridley St", "aliases": "", "active": True,
                "verified": True,
            },
            {
                "site_key": "pocatello", "name": "444 Pocatello Dr, San Jose, CA 95111",
                "full_address": "444 Pocatello Dr, San Jose, CA 95111",
                "address_line_1": "444 Pocatello Dr", "aliases": "", "active": True,
                "verified": True,
            },
        ])
        unresolved = resolver.resolve("444 =")
        self.assertFalse(unresolved["matched"])
        self.assertEqual(unresolved["name"], "444 =")
        self.assertEqual(unresolved["method"], "ambiguous")
        self.assertEqual(len(unresolved["possible_matches"]), 2)

    def test_same_number_with_different_street_name_is_not_merged(self):
        resolver = SiteResolver([{
            "site_key": "lowery", "name": "2 Lowery Dr, Atherton, CA 94027",
            "full_address": "2 Lowery Dr, Atherton, CA 94027",
            "address_line_1": "2 Lowery Dr", "aliases": "", "active": True,
            "verified": True,
        }])
        self.assertFalse(resolver.resolve("2 Campo Bello Ln")["matched"])
        self.assertTrue(resolver.resolve("2")["matched"])

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
