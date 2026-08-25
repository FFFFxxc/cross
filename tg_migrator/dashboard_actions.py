from __future__ import annotations

import asyncio
from typing import Any

from .state import DashboardAction, MigrationState


def _required_text(payload: dict[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Поле {key} должно быть непустой строкой.")
    return value.strip()


def _optional_text(payload: dict[str, object], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"Поле {key} должно быть строкой.")
    return value.strip()


def _positive_count(payload: dict[str, object], key: str) -> int:
    value = payload.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"Поле {key} должно быть положительным целым числом.")
    return min(value, 1000)


class DashboardActionRunner:
    def __init__(self, state: MigrationState, controller: Any):
        self.state = state
        self.controller = controller

    async def _execute(self, action: DashboardAction) -> dict[str, object]:
        payload = action.payload
        if action.kind == "publish_now":
            item_id = _required_text(payload, "item_id")
            if action.queue_item_id is not None and action.queue_item_id != item_id:
                raise ValueError("ID действия не совпадает с элементом очереди.")
            await self.controller.publish_item(item_id)
            saved = self.state.queue_item(item_id)
            return {
                "item_id": item_id,
                "max_mid": saved.max_mid if saved is not None else None,
            }

        if action.kind == "add_source":
            source = _required_text(payload, "source")
            peer, added = await self.controller.add_source(source)
            self.state.update_source_availability(peer, "available")
            return {"source": peer, "added": bool(added)}

        if action.kind == "remove_source":
            source = _required_text(payload, "source")
            removed = await self.controller.remove_source(source)
            return {"source": source, "removed": bool(removed)}

        if action.kind == "scan":
            count = _positive_count(payload, "count")
            source = _optional_text(payload, "source")
            kind = _optional_text(payload, "kind") or "any"
            if kind not in {"any", "video", "image"}:
                raise ValueError("Поле kind: any, video или image.")
            added = await self.controller.parse_latest(
                count,
                source,
                required_kind=kind,
            )
            return {"added": int(added)}

        if action.kind == "retry":
            item_id = _required_text(payload, "item_id")
            if not self.state.retry(item_id):
                raise ValueError("Элемент с ошибкой не найден.")
            return {"item_id": item_id, "retried": True}

        if action.kind == "max_probe":
            mid = await self.controller.publisher.max_client.send(
                "Проверка связи Desiree",
                [],
            )
            return {"max_mid": str(mid)}

        raise ValueError(f"Неизвестное действие: {action.kind}.")

    async def run_once(self) -> bool:
        action = self.state.claim_action()
        if action is None:
            return False
        try:
            result = await self._execute(action)
        except Exception as exc:
            if action.kind == "add_source":
                source = action.payload.get("source")
                if isinstance(source, str):
                    self.state.update_source_availability(
                        source,
                        "unavailable",
                        str(exc),
                    )
            self.state.fail_action(
                action.id,
                f"{exc.__class__.__name__}: {exc}",
            )
        else:
            self.state.complete_action(action.id, result)
        return True

    async def loop(self, sleep=asyncio.sleep) -> None:
        while True:
            if not await self.run_once():
                await sleep(5)
