import copy
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from typer.testing import CliRunner

from catchtable_cli.cli import app
from catchtable_cli.client import CatchTableClient
from catchtable_cli.requests import policy_request
from catchtable_cli.schema import get_command_schema
from catchtable_cli.shop_details import normalize_menu, normalize_policy

ROOT = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((ROOT / f"{name}.json").read_text())


class ShopDetailsTests(unittest.TestCase):
    def test_notice_one_won_is_not_a_real_price(self):
        result = normalize_menu(fixture("menu_notice"))
        self.assertEqual(result["items"], [])
        self.assertEqual(result["price_status"], "unknown")
        self.assertIsNone(result["notices"][0]["price_min"])
        self.assertEqual(result["notices"][0]["source_price_min"], "1")
        self.assertTrue(result["alcohol_order_required"])

    def test_real_category_menu_keeps_prices_and_description(self):
        result = normalize_menu(fixture("menu_category"))
        self.assertEqual(result["items"][0]["category"], "야키토리")
        self.assertEqual(result["items"][0]["price_min"], 24000)
        self.assertEqual(result["items"][0]["price_max"], 24000)
        self.assertIn("육류4종", result["items"][0]["description"])

    def test_missing_and_invalid_prices_are_not_free(self):
        for price in [None, "", "0", "1", "NaN", True, "-100", "시가"]:
            output = normalize_menu({"menus": [{"name": "사시미", "minPrice": price}]})
            self.assertEqual(output["items"][0]["price_status"], "unknown")
            self.assertIsNone(output["items"][0]["price_min"])

    def test_team_cap_not_multiplied_by_party_size(self):
        output = normalize_policy(fixture("policy_capped"), 2)
        self.assertEqual(output["base_deposit_total"], 10000)
        self.assertEqual(output["deposit_status"], "conditional")
        self.assertIsNone(output["deposit_required"])
        self.assertIsNone(output["deposit_total"])
        self.assertTrue(output["zero_deposit_option"]["available"])
        self.assertEqual(output["zero_deposit_option"]["upfront_amount"], 0)
        self.assertTrue(output["zero_deposit_option"]["requires_catchpay_card"])
        self.assertFalse(output["zero_deposit_option"]["user_eligibility_verified"])
        self.assertEqual(output["table_options"][0]["deposit_status"], "conditional")
        self.assertIsNone(output["table_options"][0]["deposit_total"])
        self.assertEqual(output["refund_policies"][0]["label"], "노쇼")
        self.assertEqual(output["refund_policies"][1]["refund_percent"], 20)
        self.assertEqual(output["refund_policies"][2]["refund_percent"], 50)

    def test_per_person_deposit_and_table_filter(self):
        output = normalize_policy(fixture("policy_per_person"), 2, "H")
        self.assertEqual(output["base_deposit_total"], 20000)
        self.assertEqual(output["deposit_status"], "conditional")
        self.assertEqual(len(output["table_options"]), 1)
        self.assertEqual(output["table_options"][0]["table_type"], "H")
        self.assertEqual(
            normalize_policy(fixture("policy_per_person"), 2, "PRIVATE")[
                "deposit_status"
            ],
            "unavailable",
        )

    def test_empty_menu_is_no_basic_deposit_not_no_cancellation_policy(self):
        output = normalize_policy(fixture("policy_none"), 2)
        self.assertEqual(output["deposit_status"], "none")
        self.assertEqual(output["deposit_total"], 0)
        self.assertFalse(output["deposit_required"])
        self.assertTrue(output["refund_policies"])

    def test_zero_option_false_and_missing_are_distinct(self):
        base = fixture("policy_capped")
        base["data"]["reservationPenaltyAvailable"] = False
        output = normalize_policy(base, 2)
        self.assertEqual(output["deposit_status"], "required")
        self.assertEqual(output["deposit_total"], 10000)
        self.assertTrue(output["deposit_required"])
        for flag in [None, "true", 1]:
            base["data"]["reservationPenaltyAvailable"] = flag
            output = normalize_policy(base, 2)
            self.assertEqual(output["deposit_status"], "unknown")
            self.assertIsNone(output["deposit_total"])
            self.assertEqual(output["base_deposit_total"], 10000)
            self.assertIsNone(output["zero_deposit_option"]["available"])

    def test_no_slot_does_not_mean_no_deposit(self):
        output = normalize_policy(fixture("policy_unavailable"), 2)
        self.assertEqual(output["deposit_status"], "unavailable")
        self.assertIsNone(output["deposit_required"])
        self.assertIsNone(output["deposit_total"])
        self.assertIsNone(output["zero_deposit_option"]["available"])

    def test_missing_menu_and_future_types_preserve_unknown(self):
        base = fixture("policy_capped")
        for menu in [
            {"menuType": "FUTURE"},
            {"menuType": "DEPOSIT_PER_MAN", "amountPerPerson": 10000},
        ]:
            base["data"]["defaultTable"]["menuSets"] = [menu]
            self.assertEqual(normalize_policy(base, 2)["deposit_status"], "unknown")
        del base["data"]["defaultTable"]["menuSets"]
        self.assertIsNone(normalize_policy(base, 2)["deposit_total"])

    def test_menu_purchase_and_addon_require_selection(self):
        base = fixture("policy_capped")
        base["data"]["defaultTable"]["menuSets"][0]["menuType"] = "MENU"
        self.assertEqual(
            normalize_policy(base, 2)["deposit_status"], "selection_required"
        )
        base = fixture("policy_none")
        base["data"]["defaultTable"]["addons"] = [{"itemId": 1}]
        self.assertIsNone(normalize_policy(base, 2)["deposit_required"])

    def test_table_prices_differ_do_not_pretend_one_amount(self):
        base = fixture("policy_per_person")
        base["data"]["tables"][1]["menuSets"][0]["amountPerPerson"] = 20000
        self.assertEqual(
            normalize_policy(base, 2)["deposit_status"], "selection_required"
        )

    def test_malformed_payloads_fail(self):
        for payload in [
            {},
            {"data": {"hasEmptySlot": "true"}},
            {"data": {"hasEmptySlot": True, "tables": {}}},
        ]:
            with self.assertRaises(RuntimeError):
                normalize_policy(payload, 2)
        with self.assertRaises(RuntimeError):
            normalize_menu({})

    def test_request_contract_and_midnight_input(self):
        request = policy_request("ref", "2026-10-14", "18:00", 2)
        self.assertEqual(
            request.params,
            {"shopRef": "ref", "date": "261014", "time": "1800", "personCount": "2"},
        )
        with self.assertRaises(ValueError):
            policy_request("ref", "2026-10-14", "25:00", 2)

    def test_cli_is_get_only_and_dry_run_does_not_connect(self):
        calls = []
        payload = fixture("policy_capped")

        async def request(client, method, url, **kwargs):
            calls.append((method, url, kwargs))
            if url.endswith("reservation-options"):
                return copy.deepcopy(payload)
            if url.endswith("tabs/menu"):
                return fixture("menu_notice")
            return fixture("shop")

        runner = CliRunner()
        args = [
            "shop",
            "policy",
            "test",
            "--date",
            "2026-10-14",
            "--time",
            "18:00",
            "-p",
            "2",
        ]
        with (
            patch.object(CatchTableClient, "_request", request),
            patch("catchtable_cli.credentials.read_cookie", return_value=""),
        ):
            for command in [args, ["shop", "menu", "test"]]:
                result = runner.invoke(app, command + ["--dry-run"])
                self.assertEqual(result.exit_code, 0, result.output)
            self.assertFalse(calls)
            for fmt in ["json", "table", "compact"]:
                result = runner.invoke(app, args + ["--format", fmt])
                self.assertEqual(result.exit_code, 0, (result.output, result.exception))
                if fmt == "json":
                    self.assertEqual(
                        json.loads(result.stdout)["deposit_status"], "conditional"
                    )
                else:
                    self.assertIn("0원", result.output)
            for fmt in ["json", "table", "compact"]:
                result = runner.invoke(app, ["shop", "menu", "test", "--format", fmt])
                self.assertEqual(result.exit_code, 0, result.output)
            self.assertTrue(all(method == "GET" for method, _, _ in calls))
            self.assertFalse(
                any(
                    "holdings" in url or "create" in url or url.endswith("/form")
                    for _, url, _ in calls
                )
            )
            payload = fixture("policy_unavailable")
            result = runner.invoke(app, args)
            self.assertEqual(result.exit_code, 5, result.output)
            self.assertIsNone(json.loads(result.stdout)["deposit_required"])
            for flag, value in [
                ("--date", "2026-02-30"),
                ("--time", "25:00"),
                ("-p", "0"),
            ]:
                invalid = args.copy()
                invalid[invalid.index(flag) + 1] = value
                count = len(calls)
                self.assertEqual(runner.invoke(app, invalid).exit_code, 2)
                self.assertEqual(len(calls), count)
        for command in ["shop menu", "shop policy"]:
            self.assertIsNotNone(get_command_schema(command))


if __name__ == "__main__":
    unittest.main()
