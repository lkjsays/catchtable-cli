import json
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
from typer.main import get_command
from typer.testing import CliRunner

from catchtable_cli.cli import app
from catchtable_cli.client import CatchTableAPIError, CatchTableClient
from catchtable_cli.models import DaySlot, SearchShop
from catchtable_cli.requests import REGIONS_PATH, SEARCH_PATH
from catchtable_cli.schema import get_command_schema, list_commands

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((FIXTURES / f"{name}.json").read_text())


class CliTests(unittest.TestCase):
    def setUp(self):
        self.calls = []
        self.runner = CliRunner()
        self.slot_error = None
        self.slot_payload = fixture("day_slots")
        self.search_error = None
        self.auto_payload = fixture("autocomplete")

        async def request(client, method, url, **kwargs):
            self.calls.append(
                {
                    "method": method,
                    "url": url,
                    "body": kwargs.get("json_body"),
                    "params": kwargs.get("params"),
                }
            )
            if url == REGIONS_PATH:
                return fixture("regions")
            if url == SEARCH_PATH:
                if self.search_error:
                    raise self.search_error
                return fixture("search")
            if "autocomplete" in url:
                return self.auto_payload
            if "day-slots" in url:
                if self.slot_error:
                    raise self.slot_error
                return self.slot_payload
            return fixture("shop")

        self.mock = patch.object(CatchTableClient, "_request", request)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def invoke(self, args, code=0):
        result = self.runner.invoke(app, args)
        self.assertEqual(result.exit_code, code, (result.output, result.exception))
        self.assertNotIn("Traceback", result.output)
        return result

    def test_autocomplete_limit_all_formats(self):
        for fmt in ["json", "compact", "table"]:
            with self.subTest(fmt=fmt):
                r = self.invoke(
                    [
                        "search",
                        "search",
                        "스시",
                        "--limit",
                        "2",
                        "--format",
                        fmt,
                        "--fields",
                        "label,item_type",
                    ]
                )
                if fmt == "json":
                    data = json.loads(r.stdout)
                    self.assertEqual(len(data["items"]), 2)
                    self.assertEqual(
                        data["items"][0],
                        {"label": "스시,초밥", "item_type": "FOOD_KIND"},
                    )
                    self.assertEqual(data["returned"], 2)
                    self.assertEqual(data["total"], 5)
                else:
                    self.assertNotIn("스시이안엔제주", r.output)
                    self.assertIn("FOOD_KIND", r.output)
                    if fmt == "compact":
                        self.assertEqual(len(r.stdout.splitlines()), 2)

    def test_unfiltered_json_limit(self):
        data = json.loads(
            self.invoke(["search", "search", "스시", "--limit", "2"]).stdout
        )
        self.assertEqual(len(data["items"]), 2)
        self.assertIn("code", data["items"][0])

    def test_autocomplete_passthrough_and_preview_match(self):
        args = [
            "search",
            "search",
            "스시",
            "--json-body",
            '{"query":"한우","extra":"test"}',
            "--params",
            "test=1",
        ]
        plan = json.loads(self.invoke(args + ["--dry-run"]).stdout)
        self.assertFalse(self.calls)
        self.invoke(args)
        self.assertEqual(
            self.calls, [{k: plan[k] for k in ("method", "url", "body", "params")}]
        )

    def test_region_resolution_and_preview_match(self):
        for region, code in [
            ("강남", "CAT011001"),
            ("부산", "CAT026"),
            ("CAT026", "CAT026"),
        ]:
            with self.subTest(region=region):
                self.calls.clear()
                args = [
                    "search",
                    "region",
                    "--region",
                    region,
                    "--food-kind",
                    "E_31",
                    "--visit-date",
                    "2026-10-17",
                    "--person-count",
                    "4",
                    "--sort",
                    "REVIEW",
                    "--page-size",
                    "3",
                    "--cursor",
                    "3:4:5-3:4:5",
                    "--params",
                    "test=1",
                ]
                plan = json.loads(self.invoke(args + ["--dry-run"]).stdout)
                self.assertFalse(self.calls)
                self.invoke(args)
                first = {k: v for k, v in plan["steps"][0].items() if k != "resolve"}
                second = plan["steps"][1]
                second["body"]["filters"]["displayRegionCodes"] = [code]
                self.assertEqual(self.calls, [first, second])
                self.assertEqual(second["body"]["sort"], {"sortType": "review_count"})
                self.assertEqual(
                    second["body"]["reservationParams"],
                    {"reservationDate": "2026-10-17", "personCount": 4},
                )

    def test_raw_region_does_not_resolve_or_drop_fields(self):
        body = {
            "filters": {"displayRegionCodes": ["CAT026"]},
            "paging": {"offset": "0", "size": 2},
            "extra": "test",
        }
        args = [
            "search",
            "region",
            "--region",
            "강남",
            "--json-body",
            json.dumps(body),
            "--params",
            "a=b",
        ]
        plan = json.loads(self.invoke(args + ["--dry-run"]).stdout)
        self.assertFalse(self.calls)
        self.invoke(args)
        self.assertEqual(self.calls, plan["steps"])
        self.assertEqual(self.calls[0]["body"], body)

    def test_region_output_cursor_and_dining(self):
        data = json.loads(self.invoke(["search", "region", "--region", "강남"]).stdout)
        self.assertEqual(len(data["items"]), 3)
        self.assertEqual(
            data["items"][0]["dining"]["singleDateSlotInfo"]["personCount"], 4
        )
        self.assertEqual(
            data["next_cursor"], fixture("search")["data"]["paging"]["nextOffset"]
        )

    def test_keyword_search_uses_real_search_and_preserves_region(self):
        args = ["search", "keyword", "우래옥", "--region", "강남", "--page-size", "3"]
        plan = json.loads(self.invoke(args + ["--dry-run"]).stdout)
        self.assertFalse(self.calls)
        self.invoke(args)
        self.assertEqual(self.calls[-1]["body"]["keywordSearch"], {"keyword": "우래옥"})
        self.assertEqual(
            self.calls[-1]["body"]["filters"]["displayRegionCodes"], ["CAT011001"]
        )
        self.assertEqual(len(plan["steps"]), 2)

    def test_unknown_region_stops_before_search(self):
        self.invoke(["search", "region", "--region", "모르는지역"], 2)
        self.assertEqual(len(self.calls), 1)

    def test_invalid_input_before_network_including_dry_run(self):
        cases = [
            ["search", "search", "스시", "--json-body", "[]"],
            ["search", "search", "스시", "--json-body", "{"],
            ["search", "search", "스시", "--json-body", '{"query":3}'],
            ["search", "search", "스시", "--json-body", "{}"],
            ["search", "search", "스시", "--params", "broken"],
            ["search", "search", "스시", "--fields", "itemType"],
            ["shop", "info", "../bad"],
            ["shop", "info", "test", "--params", "shopRef=wrong"],
            ["shop", "info", "test", "--params", "personCounts=-1"],
            ["shop", "info", "test", "--json-body", "{}"],
        ]
        for opts in [
            ["--visit-date", "2026-02-30"],
            ["--visit-date", "20261012"],
            ["--person-count", "-1"],
            ["--person-count", "0"],
            ["--person-count", "2"],
            ["--sort", "DISTANCE"],
            ["--category", "한식"],
            ["--page", "2"],
            ["--json-body", "[]"],
            ["--json-body", '{"region":"부산"}'],
            ["--json-body", '{"paging":{"size":true}}'],
            ["--json-body", '{"reservationParams":{"personCount":0}}'],
            ["--json-body", '{"reservationParams":{"reservationDate":"2026-02-30"}}'],
            ["--json-body", '{"filters":{"foodKindCodes":"E_31"}}'],
            ["--json-body", '{"paging":{"offset":3}}'],
        ]:
            cases.append(["search", "region", "--region", "강남"] + opts)
        for args in cases:
            for dry in [[], ["--dry-run"]]:
                with self.subTest(args=args + dry):
                    self.calls.clear()
                    self.invoke(args + dry, 2)
                    self.assertFalse(self.calls)

    def test_shop_preview_and_scoped_params(self):
        args = [
            "shop",
            "info",
            "bornandbredoriginal",
            "--params",
            "personCounts=2,test=1",
        ]
        plan = json.loads(self.invoke(args + ["--dry-run"]).stdout)
        self.assertFalse(self.calls)
        self.invoke(args)
        second = plan["steps"][1]
        second.pop("resolve")
        second["params"]["shopRef"] = fixture("shop")["data"]["shopDetailVO"]["shopRef"]
        self.assertEqual(self.calls, plan["steps"])
        self.assertIsNone(self.calls[0]["params"])

    def test_slot_statuses_across_formats_and_fields(self):
        self.slot_payload = {
            "data": [
                {
                    "date": "2026-10-17",
                    "availableStatus": "AVAILABLE",
                    "availablePersonCounts": [2, 4],
                },
                {
                    "date": "2026-10-18",
                    "availableStatus": "NEW_STATUS",
                    "availablePersonCounts": [],
                },
                {
                    "date": "2026-10-19",
                    "availableStatus": "DAY_OFF",
                    "availablePersonCounts": [],
                },
            ]
        }
        for fmt in ["json", "compact", "table"]:
            r = self.invoke(
                ["shop", "info", "test", "--format", fmt, "--fields", "shop_name"]
            )
            if fmt == "json":
                d = json.loads(r.stdout)
                self.assertEqual(set(d["shop"]), {"shop_name"})
                self.assertEqual(
                    [s["is_available"] for s in d["day_slots"]], [True, None, False]
                )
                self.assertEqual(d["day_slots"][0]["available_person_counts"], [2, 4])
            elif fmt == "compact":
                self.assertIn("2026-10-18\tNEW_STATUS\t-\t[]", r.stdout)
                self.assertIn("2026-10-17\tAVAILABLE\tY\t[2, 4]", r.stdout)
            else:
                self.assertIn("NEW_STATUS", r.stderr)

    def test_partial_failure_all_formats_and_fields(self):
        self.slot_error = CatchTableAPIError("401", "로그인 필요")
        for fmt in ["json", "compact", "table"]:
            r = self.invoke(
                ["shop", "info", "test", "--format", fmt, "--fields", "shop_name"], 4
            )
            self.assertIn("예약 날짜 조회 실패", r.stderr)
            if fmt == "json":
                d = json.loads(r.stdout)
                self.assertFalse(d["ok"])
                self.assertTrue(d["partial"])
                self.assertEqual(d["day_slots_status"], "error")
                self.assertEqual(d["errors"][0]["code"], 3)
                self.assertTrue(d["shop"])

    def test_empty_and_malformed_slots_are_distinct(self):
        self.slot_payload = {"data": []}
        d = json.loads(self.invoke(["shop", "info", "test"]).stdout)
        self.assertEqual(d["day_slots_status"], "empty")
        self.slot_payload = {"data": {"wrong": []}}
        d = json.loads(self.invoke(["shop", "info", "test"], 4).stdout)
        self.assertEqual(d["day_slots_status"], "error")

    def test_error_codes(self):
        for exc, code in [
            (CatchTableAPIError("AUTH", "auth"), 3),
            (CatchTableAPIError("ERROR", "failure"), 1),
            (httpx.ConnectError("offline"), 1),
            (ValueError("bad JSON"), 1),
        ]:
            with self.subTest(exc=exc):
                self.search_error = exc
                self.invoke(["search", "region", "--region", "강남"], code)
        self.invoke(["schema", "show", "invalid"], 2)

    def test_suggest_uses_one_more_request(self):
        self.auto_payload = {"data": {"suggestions": []}}
        self.invoke(["search", "search", "스시", "--suggest"])
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[1]["body"], {"query": "스"})

    def test_schema_matches_help_and_normalized_fields(self):
        for command in list_commands():
            s = get_command_schema(command)
            c = get_command(app)
            for part in command.split():
                c = c.commands[part]
            self.assertEqual(set(s["parameters"]), {p.opts[0] for p in c.params})
            self.assertEqual(s["exit_codes"]["2"], "입력 오류")
        self.assertNotIn("--json-body", get_command_schema("shop info")["parameters"])
        self.assertIn(
            "item_type",
            get_command_schema("search search")["field_model"]["properties"],
        )
        self.assertNotIn("--page", get_command_schema("search region")["parameters"])

    def test_schema_numeric_boolean_and_choice_types(self):
        parameters = get_command_schema("recommend")["parameters"]
        self.assertEqual(parameters["--min-rating"]["type"], "number")
        self.assertEqual(parameters["--person-count"]["type"], "integer")
        self.assertEqual(parameters["--dry-run"]["type"], "boolean")
        self.assertEqual(parameters["--format"]["enum"], ["json", "table", "compact"])


class ModelTests(unittest.TestCase):
    def test_observed_slots(self):
        slots = [DaySlot.model_validate(s) for s in fixture("day_slots")["data"]]
        self.assertTrue(all(s.status_code in {"DAY_OFF", "CLOSED"} for s in slots))
        self.assertTrue(all(s.is_available is False for s in slots))

    def test_unknown_and_phone_are_not_unavailable(self):
        for status in [None, "UNKNOWN", "PHONE_INQUIRY"]:
            self.assertIsNone(
                DaySlot.model_validate({"availableStatus": status}).is_available
            )

    def test_zero_stats_preserved(self):
        shop = SearchShop.from_shop_result(
            {"shopMeta": {"stats": {"totalCount": 0, "avgTotalScore": 0}}}
        )
        self.assertEqual(shop.review_count, 0)
        self.assertEqual(shop.avg_rating, 0)


if __name__ == "__main__":
    unittest.main()
