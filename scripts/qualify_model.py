"""Qualify an LLM for Synapse by running the key behaviours against a controlled
fake calendar with known events — so model-specific issues (hallucination,
tool-calling failure, reasoning leaks) are caught in ONE automated run instead of
by trial-and-error in Telegram.

Usage:
    poetry run python -m scripts.qualify_model                 # the model in .env
    poetry run python -m scripts.qualify_model openai/gpt-oss-120b
    poetry run python -m scripts.qualify_model gemini-flash-lite-latest --provider gemini

Uses a FAKE calendar (no real events touched) seeded with three known events, so
any event the model reports that is not seeded is a hallucination and is flagged.
"""

from __future__ import annotations

import argparse
import asyncio
import time
from datetime import datetime, timedelta

from langgraph.checkpoint.memory import MemorySaver

from synapse.agents.calendar import build_calendar_worker_spec
from synapse.agents.manager import build_manager_graph
from synapse.bootstrap import configure_observability
from synapse.config.settings import LLMProvider, ModelSpec, Settings, get_settings
from synapse.graph.runner import run_turn
from synapse.infrastructure.llm_factory import LLMFactory
from synapse.services.calendar.models import CalendarEvent

# Ground truth: exactly these events exist. Any other title in a listing is a
# fabrication. "Standup"/"Project Review"/"Team Lunch" are common LLM inventions.
#
# The events are seeded RELATIVE to today (never hard-coded dates): the agent
# resolves "this week" against the real current date, so fixed dates go stale and
# the model is handed events outside the window it asked for — which produced
# spurious "missing some events" failures. All three sit in the next few days, so
# they fall inside both a rolling-7-day and a calendar-week reading of "this week"
# and remain in the future for an open-ended "list all my events".
def _seeded_events(settings: Settings) -> list[CalendarEvent]:
    """Build the three ground-truth events relative to today, in the user's tz."""
    today = datetime.now(settings.tzinfo()).replace(hour=0, minute=0, second=0, microsecond=0)

    def at(days: int, hour: int, minute: int = 0) -> datetime:
        return today + timedelta(days=days, hours=hour, minutes=minute)

    return [
        CalendarEvent(id="s1", summary="Scrum meeting",
                      start=at(1, 16).isoformat(), end=at(1, 16, 30).isoformat()),
        CalendarEvent(id="s2", summary="Sync",
                      start=at(2, 16).isoformat(), end=at(2, 16, 30).isoformat()),
        CalendarEvent(id="s3", summary="lunch",
                      start=at(3, 13).isoformat(), end=at(3, 14).isoformat()),
    ]


_REAL_TITLES = {"scrum", "sync", "lunch"}
_COMMON_FABRICATIONS = ("project review", "team lunch", "client meeting", "standup", "1:1", "daily standup")


class _FakeCalendar:
    def __init__(self, events: list[CalendarEvent]) -> None:
        self._events = events
        self.created: list[str] = []
        self.deleted: list[str] = []

    async def list_events(self, *, time_min, time_max, max_results):
        return list(self._events)

    async def check_availability(self, *, time_min, time_max):
        return []

    async def create_event(self, *, summary, start, end, location=None, description=None):
        self.created.append(summary)
        return CalendarEvent(id="new", summary=summary, start=start.isoformat(), end=end.isoformat())

    async def delete_event(self, *, event_id):
        self.deleted.append(event_id)


def _factory(settings: Settings, provider: LLMProvider, model: str) -> LLMFactory:
    keys = {p: settings.api_key_for(p) for p in LLMProvider}

    class _Pin(LLMFactory):
        def create(self, spec: ModelSpec):
            return super().create(spec.model_copy(update={"provider": provider, "model": model}))

    return _Pin(keys, groq_reasoning_format=settings.groq_reasoning_format)


async def _run(
    settings: Settings,
    provider: LLMProvider,
    model: str,
    text: str,
    events: list[CalendarEvent],
) -> tuple[str, _FakeCalendar, float]:
    cal = _FakeCalendar(events)
    spec = build_calendar_worker_spec(settings, gateway=cal)
    graph = build_manager_graph(
        MemorySaver(), llm_factory=_factory(settings, provider, model), settings=settings, worker_specs=[spec]
    )
    start = time.perf_counter()
    reply = await run_turn(graph, thread_id=f"qual-{text[:10]}", user_text=text)
    return reply, cal, time.perf_counter() - start


async def qualify(provider: LLMProvider, model: str) -> bool:
    settings = get_settings()
    checks: list[tuple[str, bool, str]] = []
    total_latency = 0.0

    events = _seeded_events(settings)
    # Derived from the seeded data so the checks follow the fixture: the tz offset
    # the events carry, and the date phrasing the delete request must name.
    utc_offset = events[0].start[-6:]
    scrum_start = datetime.fromisoformat(events[0].start)
    scrum_date_phrase = scrum_start.strftime("%d %B").lstrip("0")

    # 1. Listing: all three real events, and NOTHING invented.
    reply, _, secs = await _run(settings, provider, model, "list all my events this week", events)
    total_latency += secs
    low = reply.lower()
    all_real = all(t in low for t in _REAL_TITLES)
    fabricated = [f for f in _COMMON_FABRICATIONS if f in low]
    leaked_iso = utc_offset in reply or "t16:00:00" in low
    checks.append(("lists all 3 real events", all_real, "" if all_real else "missing some events"))
    checks.append(("no fabricated events", not fabricated, f"invented {fabricated}" if fabricated else ""))
    checks.append(("no raw ISO leaked", not leaked_iso, "raw timestamp in reply" if leaked_iso else ""))

    # 2. Create routes and reaches an approval gate (no silent write).
    reply, cal, secs = await _run(
        settings, provider, model, "schedule a meeting called QualTest tomorrow at 4pm", events
    )
    total_latency += secs
    asked_approval = "yes" in reply.lower() and "confirm" in reply.lower()
    checks.append(("create asks for approval", asked_approval, "" if asked_approval else f"no approval prompt: {reply[:60]!r}"))
    checks.append(("nothing created before approval", not cal.created, "created without approval!" if cal.created else ""))

    # 3. Delete is routed (not refused as 'I cannot delete').
    reply, _, secs = await _run(
        settings, provider, model, f"delete the Scrum meeting on {scrum_date_phrase}", events
    )
    total_latency += secs
    refused = "not able to delete" in reply.lower() or "cannot delete" in reply.lower() or "can't delete" in reply.lower()
    checks.append(("delete is not refused", not refused, "Manager refused to route delete" if refused else ""))

    passed = sum(1 for _, ok, _ in checks if ok)
    print(f"\n=== Model qualification: {provider.value} / {model} ===")
    for name, ok, detail in checks:
        print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not ok else ""))
    print(f"\n  {passed}/{len(checks)} checks passed   |   avg latency {total_latency / 3:.1f}s/turn")
    verdict = passed == len(checks)
    print("  VERDICT:", "READY" if verdict else "NOT RECOMMENDED")
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser(description="Qualify an LLM for Synapse.")
    parser.add_argument("model", nargs="?", help="Model name (defaults to .env).")
    parser.add_argument("--provider", choices=[p.value for p in LLMProvider], help="Provider (defaults to .env).")
    args = parser.parse_args()

    settings = get_settings()
    configure_observability(settings)
    provider = LLMProvider(args.provider) if args.provider else settings.default_llm_provider
    model = args.model or settings.default_llm_model

    ready = asyncio.run(qualify(provider, model))
    return 0 if ready else 1


if __name__ == "__main__":
    raise SystemExit(main())
