import base64
import json
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from typer.testing import CliRunner

from catchtable_cli.cli import app
from catchtable_cli.client import CatchTableClient
from catchtable_cli.commands.recommend import rank_shops
from catchtable_cli.config import mask_value
from catchtable_cli.dining import (
    ISSUE_KEY_PATH,
    TIME_SLOTS_PATH,
)
from catchtable_cli.requests import REGIONS_PATH, SEARCH_PATH

ROOT = Path(__file__).parent / "fixtures"


def fixture(name):
    return json.loads((ROOT / f"{name}.json").read_text())


def times():
    return {
        "data": {
            "state": 200,
            "personCount": 2,
            "timeSlotMap": {
                "1200": {
                    "availableYn": True,
                    "date": "261018",
                    "personCount": 2,
                    "periodGubun": "L",
                    "tableType": "B",
                },
                "1800": {
                    "availableYn": False,
                    "date": "261018",
                    "personCount": 2,
                    "periodGubun": "D",
                },
                "0100": {
                    "availableYn": True,
                    "date": "261018",
                    "personCount": 2,
                    "periodGubun": "D",
                },
            },
        }
    }


class DiningTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        cls.rsa = {
            "slotEncPublicKey": cls.key.public_key()
            .public_bytes(Encoding.PEM, PublicFormat.SubjectPublicKeyInfo)
            .decode(),
            "c1": 1,
            "c2": 2,
            "c3": 3,
            "c4": 4,
        }

    def setUp(self):
        self.calls = []
        self.time_payload = times()
        self.runner = CliRunner()
        self.credential_patch = patch(
            "catchtable_cli.credentials.read_cookie", return_value=""
        )
        self.credential_patch.start()
        self.addCleanup(self.credential_patch.stop)

        async def request(client, method, url, **kwargs):
            self.calls.append((method, url, kwargs))
            if url == ISSUE_KEY_PATH:
                return {"data": {"rsa": self.rsa}}
            if url == TIME_SLOTS_PATH:
                encrypted = kwargs["json_body"]["encryptedParamString"]
                plaintext = json.loads(
                    self.key.decrypt(base64.b64decode(encrypted), PKCS1v15())
                )
                self.assertEqual(plaintext["searchDate"], "2026-10-18")
                self.assertEqual(plaintext["personCount"], 2)
                self.assertEqual(plaintext["tableType"], "_ALL_")
                return self.time_payload
            if url == REGIONS_PATH:
                return fixture("regions")
            if url == SEARCH_PATH:
                return fixture("search")
            if url == "/api/v3/user/myMain":
                return {"data": {"user": {"displayName": "test"}}}
            if url == "/api/v4/user/reservations/_list":
                return {"data": {"reservations": [], "hasMore": False}}
            return fixture("shop")

        self.request_patch = patch.object(CatchTableClient, "_request", request)
        self.request_patch.start()
        self.addCleanup(self.request_patch.stop)

    def invoke(self, args, code=0, **kwargs):
        r = self.runner.invoke(app, args, **kwargs)
        self.assertEqual(r.exit_code, code, (r.output, r.exception))
        return r

    def test_rsa_encrypts_actual_request_and_transmits_challenge(self):
        r = self.invoke(
            ["shop", "availability", "test", "--date", "2026-10-18", "-p", "2"]
        )
        d = json.loads(r.stdout)
        self.assertEqual(d["availability_status"], "available")
        self.assertEqual(d["slots"][-1]["service_time"], "25:00")
        self.assertEqual(d["slots"][-1]["date"], "2026-10-19")
        self.assertEqual(self.calls[-1][2]["json_body"]["c4"], 4)
        self.assertNotIn("encryptedParamString", r.stdout)

    def test_dry_runs_do_not_issue_keys_or_reserve(self):
        commands = [
            ["shop", "availability", "test", "--date", "2026-10-18", "-p", "2"],
            ["reserve", "test", "--date", "2026-10-18", "--time", "12:00", "-p", "2"],
            ["recommend", "--region", "강남"],
            ["reservations", "list"],
        ]
        for args in commands:
            self.invoke(args + ["--dry-run"])
        self.assertFalse(self.calls)

    def test_reserve_handoff_checks_slot_and_never_mutates(self):
        r = self.invoke(
            ["reserve", "test", "--date", "2026-10-18", "--time", "12:00", "-p", "2"]
        )
        d = json.loads(r.stdout)
        self.assertEqual(d["status"], "ready_for_browser")
        self.assertFalse(d["reservation_created"])
        self.assertIn("time=1200", d["booking_url"])
        self.assertTrue(
            all(
                "/create" not in url and "/holdings" not in url
                for _, url, _ in self.calls
            )
        )

    def test_reserve_unavailable_is_nonzero(self):
        r = self.invoke(
            ["reserve", "test", "--date", "2026-10-18", "--time", "18:00", "-p", "2"], 5
        )
        d = json.loads(r.stdout)
        self.assertFalse(d["ok"])
        self.assertIsNone(d["booking_url"])
        self.assertFalse(d["reservation_created"])

    def test_invalid_reservation_inputs_before_requests(self):
        for date, time in [
            ("2026-02-30", "12:00"),
            ("2026-10-18", "30:00"),
            ("2026-10-18", "12:61"),
        ]:
            self.invoke(
                ["reserve", "test", "--date", date, "--time", time, "-p", "2"], 2
            )
        self.assertFalse(self.calls)

    def test_mismatched_api_party_is_error(self):
        self.time_payload["data"]["timeSlotMap"]["1200"]["personCount"] = 4
        self.invoke(
            ["shop", "availability", "test", "--date", "2026-10-18", "-p", "2"], 1
        )

    def test_empty_and_unknown_availability(self):
        self.time_payload["data"]["timeSlotMap"] = {}
        d = json.loads(
            self.invoke(
                ["shop", "availability", "test", "--date", "2026-10-18", "-p", "2"]
            ).stdout
        )
        self.assertEqual(d["availability_status"], "unavailable")
        self.time_payload = times()
        self.time_payload["data"]["timeSlotMap"] = {
            "1200": {"availableYn": "NEW_STATE", "periodGubun": "L"}
        }
        d = json.loads(
            self.invoke(
                ["shop", "availability", "test", "--date", "2026-10-18", "-p", "2"]
            ).stdout
        )
        self.assertEqual(d["availability_status"], "unknown")

    def test_auth_login_checks_before_store_and_never_echoes(self):
        secret = "synthetic-test-cookie"
        with patch("catchtable_cli.commands.account.save_cookie") as save:
            r = self.invoke(["auth", "login", "--cookie-stdin"], input=secret)
            save.assert_called_once_with(secret)
            self.assertNotIn(secret, r.output)
            self.assertTrue(json.loads(r.stdout)["authenticated"])
        self.assertEqual(self.calls[-1][1], "/api/v3/user/myMain")

    def test_invalid_session_is_never_stored(self):
        from catchtable_cli.client import CatchTableAPIError

        with patch.object(
            CatchTableClient,
            "_request",
            new_callable=AsyncMock,
            side_effect=CatchTableAPIError("LOGIN_REQUIRED", "expired"),
        ):
            with patch("catchtable_cli.commands.account.save_cookie") as save:
                r = self.invoke(
                    ["auth", "login", "--cookie-stdin"],
                    3,
                    input="synthetic-expired-cookie",
                )
                save.assert_not_called()
                self.assertNotIn("synthetic-expired-cookie", r.output)

    def test_unauthenticated_list_fails_without_network(self):
        self.invoke(["reservations", "list"], 3, env={"CT_SESSION_COOKIE": ""})
        self.assertFalse(self.calls)

    def test_auth_status_offline_does_not_claim_login(self):
        r = self.invoke(["auth", "status"], env={"CT_SESSION_COOKIE": ""})
        self.assertIsNone(json.loads(r.stdout)["authenticated"])
        self.assertFalse(self.calls)

    def test_reservations_list_passes_cursor(self):
        r = self.invoke(
            ["reservations", "list", "--size", "2", "--cursor", "cursor123"],
            env={"CT_SESSION_COOKIE": "synthetic"},
        )
        self.assertTrue(json.loads(r.stdout)["ok"])
        self.assertEqual(self.calls[0][2]["params"]["scrollKey"], "cursor123")

    def test_mask_even_short_secrets(self):
        for value in ["a", "abc", "long-test-cookie"]:
            self.assertEqual(mask_value(value), "***")


class RecommendationTests(unittest.TestCase):
    def test_available_type_alone_is_not_enough(self):
        shops = fixture("search")["data"]["shopResults"]["shops"][:1]
        rows = rank_shops(
            shops,
            min_rating=0,
            min_reviews=0,
            available_only=True,
            date="2026-10-17",
            person_count=4,
            limit=5,
        )
        self.assertEqual(rows, [])

    def test_ranking_respects_reviews_and_includes_evidence(self):
        shops = [
            {
                "shopMeta": {
                    "shopName": "one",
                    "stats": {"avgTotalScore": 5, "totalCount": 1},
                }
            },
            {
                "shopMeta": {
                    "shopName": "many",
                    "stats": {"avgTotalScore": 4.9, "totalCount": 500},
                }
            },
        ]
        rows = rank_shops(
            shops,
            min_rating=0,
            min_reviews=0,
            available_only=False,
            date=None,
            person_count=None,
            limit=5,
        )
        self.assertEqual(rows[0]["shop_name"], "many")
        self.assertTrue(rows[0]["reasons"])
        self.assertFalse(rows[0]["availability_verified"])
