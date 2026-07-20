import sqlite3
import unittest

from server import SCHEMA, day_record, save_day, work_day_allocations


class LocationCostCenterTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.executescript(SCHEMA)
        self.connection.execute(
            "INSERT INTO workers(id,name,normalized_name,workbook_name) "
            "VALUES(1,'Test Worker','test worker','Test Worker')"
        )
        self.connection.executemany(
            "INSERT INTO cost_centers(id,name,display_order) VALUES(?,?,?)",
            [("CC-1", "Framing", 1), ("CC-2", "Drywall", 2)],
        )

    def tearDown(self):
        self.connection.close()

    def test_locations_own_their_cost_centers(self):
        save_day(
            self.connection, 1, "2026-07-17",
            {
                "status": "worked", "total_hours": 10, "extra_pay": 0,
                "locations": [
                    {"name": "North", "hours": 4, "cost_centers": [
                        {"id": "CC-1"}, {"id": "CC-2"}
                    ]},
                    {"name": "South", "hours": 4, "cost_centers": [
                        {"id": "CC-1"}
                    ]},
                ],
            },
            "mobile-logger",
        )
        record = day_record(self.connection, 1, "2026-07-17")
        self.assertEqual(
            [[center["id"] for center in location["cost_centers"]]
             for location in record["locations"]],
            [["CC-1", "CC-2"], ["CC-1"]],
        )
        allocations = work_day_allocations(
            self.connection, "2026-07-17", "2026-07-17", 1
        )[0]
        self.assertEqual(sum(item["hours"] for item in allocations["locations"]), 10)
        self.assertEqual(sum(item["hours"] for item in allocations["cost_centers"]), 10)

    def test_logger_allows_a_location_without_a_cost_center(self):
        save_day(
            self.connection, 1, "2026-07-18",
            {
                "status": "worked", "total_hours": 8,
                "locations": [
                    {"name": "North", "hours": None, "cost_centers": []}
                ],
            },
            "mobile-logger",
        )
        record = day_record(self.connection, 1, "2026-07-18")
        self.assertEqual(record["locations"][0]["cost_centers"], [])
        allocations = work_day_allocations(
            self.connection, "2026-07-18", "2026-07-18", 1
        )[0]
        self.assertEqual(allocations["locations"][0]["hours"], 8)
        self.assertEqual(allocations["cost_centers"], [])


if __name__ == "__main__":
    unittest.main()
