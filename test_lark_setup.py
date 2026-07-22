import unittest
from unittest.mock import patch

from api.lark import setup


class LarkSetupTests(unittest.TestCase):
    def test_initialize_creates_schema_and_is_idempotent(self):
        tables = []
        fields = {}

        def list_tables(_token, _app_token):
            return [dict(item) for item in tables]

        def list_fields(_token, _app_token, table_id):
            return [dict(item) for item in fields[table_id]]

        def api(method, path, *, token, body=None, query=None):
            del token, query
            if method == "GET" and path.endswith("/apps/app-test"):
                return {
                    "code": 0,
                    "data": {
                        "app": {
                            "app_token": "app-test",
                            "name": "Workforce",
                            "time_zone": "America/Los_Angeles",
                        }
                    },
                }
            if method == "POST" and path.endswith("/tables"):
                table_id = f"tbl{len(tables) + 1}"
                table = {"name": body["table"]["name"], "table_id": table_id}
                tables.append(table)
                fields[table_id] = [
                    {
                        "field_id": f"fld{table_id}-{index}",
                        "field_name": definition["field_name"],
                        "type": definition["type"],
                        "is_primary": index == 1,
                    }
                    for index, definition in enumerate(body["table"]["fields"], start=1)
                ]
                # Current Lark Base API returns table_id directly under data.
                return {"code": 0, "data": {"table_id": table_id}}
            if method == "POST" and path.endswith("/fields"):
                table_id = path.split("/tables/", 1)[1].split("/", 1)[0]
                field = {
                    "field_id": f"fld{table_id}-{len(fields[table_id]) + 1}",
                    "field_name": body["field_name"],
                    "type": body["type"],
                    "is_primary": False,
                }
                fields[table_id].append(field)
                return {"code": 0, "data": {"field": field}}
            raise AssertionError(f"Unexpected API call: {method} {path}")

        with (
            patch.object(setup, "_tables", side_effect=list_tables),
            patch.object(setup, "_fields", side_effect=list_fields),
            patch.object(setup, "lark_api", side_effect=api),
        ):
            first = setup._initialize("tenant-test", "app-test")
            second = setup._initialize("tenant-test", "app-test")

        self.assertEqual(set(first["created_tables"]), set(setup.SCHEMA))
        self.assertTrue(first["schema"]["ready"])
        self.assertEqual(second["created_tables"], [])
        self.assertEqual(second["created_fields"], [])
        self.assertTrue(second["schema"]["ready"])


if __name__ == "__main__":
    unittest.main()
