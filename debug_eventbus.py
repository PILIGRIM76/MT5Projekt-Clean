# debug_eventbus.py
"""Минимальный тест EventBus без GUI"""

import asyncio
import logging
import sys
from pathlib import Path

# Добавляем проект в path
sys.path.insert(0, str(Path(__file__).parent))

logging.basicConfig(level=logging.DEBUG, format="%(levelname)s: %(message)s")


async def test_eventbus():
    from src.core.event_bus import EventPriority, SystemEvent, get_event_bus

    bus = get_event_bus()
    print(f"✅ EventBus создан: {bus}")

    # Тест подписки
    received = []

    async def handler(event: SystemEvent):
        received.append(event)
        print(f"📩 Получено: {event.type} = {event.payload}")

    await bus.subscribe("test_event", handler)
    print("✅ Подписка активна")

    # Тест публикации
    await bus.publish(
        SystemEvent(
            type="test_event",
            payload={"hello": "world"},
            priority=EventPriority.HIGH,
        )
    )
    await asyncio.sleep(0.1)  # Дать время на доставку

    if received:
        print("✅ Событие доставлено!")
        return True
    else:
        print("❌ Событие НЕ доставлено — EventBus сломан")
        return False


if __name__ == "__main__":
    result = asyncio.run(test_eventbus())
    sys.exit(0 if result else 1)
