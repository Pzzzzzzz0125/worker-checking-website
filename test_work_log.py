import unittest

from api._work_log import format_normalized_entry, work_log_row


class WorkLogTests(unittest.TestCase):
    def test_multiple_locations_and_cost_centers_have_one_canonical_style(self):
        day = {
            "Work Day Key": "7|2026-07-24",
            "Worker Key": "7",
            "Worker Name": "Ana",
            "Work Date": 1784876400000,
            "Status": "worked",
            "Total Hours": 10,
            "Overtime Hours": 2,
            "Extra Pay": 20,
            "Source": "web-entry",
        }
        locations = [
            {
                "Work Day Key": day["Work Day Key"],
                "Location": "444 Pocatello",
                "Start Time": "08:30",
                "End Time": "12:30",
                "Regular Hours": 2,
                "Overtime Hours": 0,
                "Cost Center ID": "100",
                "Cost Center Name": "Framing",
                "Display Order": 1,
            },
            {
                "Work Day Key": day["Work Day Key"],
                "Location": "444 Pocatello",
                "Start Time": "08:30",
                "End Time": "12:30",
                "Regular Hours": 2,
                "Overtime Hours": 0,
                "Cost Center ID": "101",
                "Cost Center Name": "Drywall",
                "Display Order": 1,
            },
            {
                "Work Day Key": day["Work Day Key"],
                "Location": "111 Main",
                "Start Time": "12:30",
                "End Time": "18:30",
                "Regular Hours": 4,
                "Overtime Hours": 2,
                "Cost Center ID": "200",
                "Cost Center Name": "Electrical",
                "Display Order": 2,
            },
        ]
        normalized = format_normalized_entry(day, locations)
        self.assertEqual(
            normalized,
            "444 Pocatello [08:30-12:30 | 4h | "
            "CC: 100 Framing (2h) + 101 Drywall (2h)]; "
            "111 Main [12:30-18:30 | 6h (4h reg + 2h ot) | "
            "CC: 200 Electrical (6h)], ot 2h, ex $20",
        )
        row = work_log_row(day, locations)
        self.assertEqual(row["Locations"], "444 Pocatello; 111 Main")
        self.assertEqual(
            row["Cost Centers"],
            "100 Framing; 101 Drywall; 200 Electrical",
        )
        self.assertEqual(row["Regular Hours"], 8)
        self.assertEqual(row["Overtime Hours"], 2)

    def test_off_reason_is_preserved(self):
        day = {
            "Status": "off",
            "Original Text": "off (vacation)",
            "Total Hours": 0,
        }
        self.assertEqual(format_normalized_entry(day, []), "off (vacation)")


if __name__ == "__main__":
    unittest.main()
