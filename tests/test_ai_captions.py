import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import httpx

from tg_migrator.ai_captions import (
    AiCaptionClient,
    AiCaptionService,
    AiProvider,
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
        return "Вот это поворот даже для сенсея 😄", providers[-1]

    async def test(self, provider):
        return f"Связь с {provider.model} есть"

    async def aclose(self):
        return None


class AiCaptionTests(unittest.IsolatedAsyncioTestCase):
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
            caption, provider = await client.generate_with_fallback(
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
