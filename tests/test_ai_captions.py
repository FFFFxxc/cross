import base64
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import patch

import httpx
from PIL import Image

from tg_migrator.ai_captions import (
    AiCaptionError,
    AiCaptionClient,
    AiCaptionService,
    AiProvider,
    AiProviderFailure,
    _clean_generated_caption,
    decrypt_secret,
    encrypt_secret,
)
from tg_migrator.state import MigrationState


class FakeTelegram:
    def __init__(self, text=""):
        self.message = SimpleNamespace(
            id=1,
            raw_text=text,
            message=text,
            entities=[],
            media=object(),
            photo=object(),
            video=None,
            document=None,
        )

    async def get_messages(self, _source, ids):
        return [self.message for _ in ids]


class FakeAiClient:
    def __init__(self):
        self.calls = []

    async def generate_with_fallback(self, providers, **kwargs):
        self.calls.append((providers, kwargs))
        return "Вот это поворот даже для сенсея 😄", providers[-1], ()

    async def test(self, provider):
        return f"Связь с {provider.model} есть"

    async def aclose(self):
        return None


class AiCaptionTests(unittest.IsolatedAsyncioTestCase):
    def set_profile(self, state, index, *models):
        prefix = f"ai_provider_{index}_"
        state.set_setting(prefix + "base_url", f"https://router{index}.example/v1")
        state.set_setting(prefix + "api_key", encrypt_secret(f"key-{index}", "secret"))
        state.set_setting(prefix + "model", models[0])
        if len(models) > 1:
            state.set_setting(prefix + "models", json.dumps(models))

    async def test_same_url_fallback_stops_at_first_valid_caption(self):
        state = MigrationState(Path(":memory:"))
        self.addCleanup(state.close)
        self.set_profile(state, 1, "broken", "blind", "vision")
        self.set_profile(state, 2, "unused")
        calls = []

        async def resolve(_url):
            pass

        async def handler(request):
            model = json.loads(request.content)["model"]
            calls.append(model)
            self.assertEqual(request.url.host, "router1.example")
            self.assertEqual(request.headers["Authorization"], "Bearer key-1")
            if model == "broken":
                return httpx.Response(429, json={"error": "key-1"})
            return httpx.Response(200, json={"choices": [{"message": {"content": "SKIP" if model == "blind" else "Опять он"}}]})

        client = AiCaptionClient(transport=httpx.MockTransport(handler), resolver=resolve)
        self.addAsyncCleanup(client.aclose)
        service = AiCaptionService(None, state, "secret", client=client)
        caption, winner, failures = await client.generate_with_fallback(
            service.providers(), image=b"test", mime_type="image/png", prompt="test", max_chars=75, context="test",
        )
        self.assertEqual(calls, ["broken", "blind", "vision"])
        self.assertEqual((caption, winner.model), ("Опять он", "vision"))
        self.assertNotIn("key-1", failures[0].error)
        for failure in failures:
            service._mark_provider_failed(failure, None)
        self.assertEqual([p.model for p in service._ordered_available_providers()], ["vision", "unused"])

    async def test_profile_check_reports_every_model_even_after_first_pass(self):
        state = MigrationState(Path(":memory:"))
        self.addCleanup(state.close)
        self.set_profile(state, 1, "vision", "blind", "backup")
        self.set_profile(state, 2, "not-tested")
        calls = []

        async def resolve(_url):
            pass

        async def handler(request):
            body = json.loads(request.content)
            calls.append(body["model"])
            encoded = body["messages"][0]["content"][1]["image_url"]["url"].split(",", 1)[1]
            with Image.open(BytesIO(base64.b64decode(encoded))) as image:
                self.assertEqual(image.getpixel((0, 0)), (255, 0, 0))
            reply = "BLUE" if body["model"] == "blind" else "RED"
            return httpx.Response(200, json={"choices": [{"message": {"content": reply}}]})

        client = AiCaptionClient(transport=httpx.MockTransport(handler), resolver=resolve)
        self.addAsyncCleanup(client.aclose)
        service = AiCaptionService(None, state, "secret", client=client)
        first = service.providers()[0]
        service._mark_provider_failed(AiProviderFailure(first, "HTTP 429"), None)
        with patch("tg_migrator.ai_captions.secrets.choice", return_value="RED"):
            result = await service.test_provider(1)
        self.assertEqual(calls, ["vision", "blind", "backup"])
        self.assertEqual([v["ok"] for v in result["models"]], [True, False, True])
        self.assertIsNotNone(service._cooldown_until(first))

    def test_legacy_or_conflicting_settings_keep_primary_model(self):
        state = MigrationState(Path(":memory:"))
        self.addCleanup(state.close)
        self.set_profile(state, 1, "legacy")
        service = AiCaptionService(None, state, "secret", client=FakeAiClient())
        self.assertEqual([p.model for p in service.providers()], ["legacy"])
        state.set_setting("ai_provider_1_models", '["old", "other"]')
        self.assertEqual([p.model for p in service.providers()], ["legacy"])

    def test_rejects_meta_answers_and_overlong_captions(self):
        invalid = (
            "Пришлите изображение и укажите желаемый тон",
            "Я не могу увидеть картинку",
            "Вот вариант подписи: обычный день героя",
            "Логика мема понятна, но подпись писать не буду",
            "I can't write a caption for this one",
            "Please upload an image first",
            "SKIP",
            "Раз два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать тринадцать",
        )
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(AiCaptionError):
                _clean_generated_caption(value, 75)

    def test_secret_round_trip_is_encrypted(self):
        encrypted = encrypt_secret("sk-secret", "postgresql://shared-secret")
        self.assertTrue(encrypted.startswith("enc:v1:"))
        self.assertNotIn("sk-secret", encrypted)
        self.assertEqual(
            decrypt_secret(encrypted, "postgresql://shared-secret"),
            "sk-secret",
        )

    async def test_openai_compatible_client_falls_back_to_second_provider(self):
        async def resolve(_url):
            return None

        async def handler(request: httpx.Request):
            if request.url.host == "first.example":
                return httpx.Response(504, json={"error": {"message": "timeout"}})
            body = __import__("json").loads(request.content)
            self.assertEqual(body["model"], "vision-two")
            self.assertEqual(body["messages"][1]["content"][1]["type"], "image_url")
            return httpx.Response(
                200,
                json={"choices": [{"message": {"content": "  Подпись к мему  "}}]},
            )

        client = AiCaptionClient(
            transport=httpx.MockTransport(handler),
            resolver=resolve,
        )
        providers = [
            AiProvider(1, "https://first.example/v1", "key-1", "vision-one"),
            AiProvider(2, "https://second.example/v1", "key-2", "vision-two"),
        ]
        try:
            caption, provider, failures = await client.generate_with_fallback(
                providers,
                image=b"webp",
                mime_type="image/webp",
                prompt="Придумай подпись",
                max_chars=120,
                context="аниме-мем",
            )
        finally:
            await client.aclose()

        self.assertEqual(caption, "Подпись к мему")
        self.assertEqual(provider.index, 2)
        self.assertEqual(len(failures), 1)

    async def test_client_falls_back_when_first_provider_cannot_see_image(self):
        async def resolve(_url):
            return None

        async def handler(request: httpx.Request):
            text = (
                "Пришлите изображение и укажите желаемый тон"
                if request.url.host == "first.example"
                else "Да ну, опять он"
            )
            return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})

        client = AiCaptionClient(transport=httpx.MockTransport(handler), resolver=resolve)
        providers = [
            AiProvider(1, "https://first.example/v1", "key-1", "vision-one"),
            AiProvider(2, "https://second.example/v1", "key-2", "vision-two"),
        ]
        try:
            caption, provider, _failures = await client.generate_with_fallback(
                providers,
                image=b"webp",
                mime_type="image/webp",
                prompt="Придумай подпись",
                max_chars=75,
                context="аниме-мем",
            )
        finally:
            await client.aclose()

        self.assertEqual(caption, "Да ну, опять он")
        self.assertEqual(provider.index, 2)

    async def test_service_generates_only_when_clean_source_text_is_empty(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            secret = "postgresql://shared-secret"
            state.set_setting("ai_enabled", "true")
            state.set_setting("ai_provider_1_base_url", "https://first.example/v1")
            state.set_setting("ai_provider_1_model", "vision-one")
            state.set_setting("ai_provider_1_api_key", encrypt_secret("key-1", secret))
            state.set_setting("ai_provider_2_base_url", "https://second.example/v1")
            state.set_setting("ai_provider_2_model", "vision-two")
            state.set_setting("ai_provider_2_api_key", encrypt_secret("key-2", secret))
            item = state.enqueue(
                "source", "message:1", (1,), "image", 10,
                datetime.now(timezone.utc),
            )
            state.update_post_metadata(
                item.id,
                preview_mime="image/webp",
                preview_data=b"preview",
            )
            fake_ai = FakeAiClient()
            service = AiCaptionService(
                FakeTelegram("НАШ ТГК https://t.me/example"),
                state,
                secret,
                client=fake_ai,
            )

            generated = await service.ensure_caption(state.queue_item(item.id))

            self.assertEqual(generated.ai_caption, "Вот это поворот даже для сенсея 😄")
            self.assertEqual(generated.ai_caption_status, "generated")
            self.assertEqual(generated.ai_caption_provider, "2:vision-two")
            self.assertEqual(len(fake_ai.calls), 1)
            self.assertEqual([p.index for p in service._ordered_available_providers()], [1, 2])
            self.assertEqual(state.recent_actions(1)[0].kind, "ai_caption_generated")
            state.close()

    async def test_service_does_not_replace_real_source_caption(self):
        with tempfile.TemporaryDirectory() as directory:
            state = MigrationState(Path(directory) / "state.sqlite3")
            state.set_setting("ai_enabled", "true")
            item = state.enqueue(
                "source", "message:1", (1,), "image", 10,
                datetime.now(timezone.utc),
            )
            state.update_post_metadata(
                item.id,
                preview_mime="image/webp",
                preview_data=b"preview",
            )
            fake_ai = FakeAiClient()
            service = AiCaptionService(
                FakeTelegram("Новый трейлер уже вышел"),
                state,
                "secret",
                client=fake_ai,
            )

            saved = await service.ensure_caption(state.queue_item(item.id))

            self.assertEqual(saved.ai_caption_status, "not_needed")
            self.assertIsNone(saved.ai_caption)
            self.assertEqual(fake_ai.calls, [])
            state.close()


if __name__ == "__main__":
    unittest.main()
