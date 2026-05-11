"""Transport abstractions for the SDK.

Two concrete transports today:

* :class:`DaemonTransport` — posts events to a running ``hutch serve``.
  On failure, the SDK either raises (strict mode) or appends the event to
  the fallback JSONL and continues.
* :class:`EmbeddedTransport` — writes events directly to a DuckDB file.
  Used in CI, notebooks, and any process that doesn't want to manage a
  separate daemon.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any

import httpx

from hutch.schema import AnyEvent
from hutch.sdk import fallback
from hutch.sdk.config import SDKConfig
from hutch.store import insert_event, open_and_migrate

if TYPE_CHECKING:
    from hutch.store.database import DuckConn

logger = logging.getLogger("hutch.sdk.transport")


class Transport(ABC):
    """Abstract event sink."""

    @abstractmethod
    def send(self, event: AnyEvent) -> None:
        """Persist ``event``. Must not raise on transient failures unless
        the SDK is in strict mode."""

    @abstractmethod
    def close(self) -> None:
        """Release any resources held by the transport."""


class EmbeddedTransport(Transport):
    """Writes events directly to a local DuckDB file."""

    def __init__(self, db_path: Path | str | None = None) -> None:
        self._db_path = Path(db_path) if db_path is not None else None
        self._conn: DuckConn | None = None

    def _get_conn(self) -> DuckConn:
        if self._conn is None:
            if self._db_path is not None:
                self._db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = open_and_migrate(self._db_path)
        return self._conn

    def send(self, event: AnyEvent) -> None:
        insert_event(self._get_conn(), event)

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


class DaemonTransport(Transport):
    """Posts events to a running ``hutch serve`` over HTTP."""

    def __init__(self, config: SDKConfig) -> None:
        self._config = config
        self._client = httpx.Client(
            base_url=config.daemon_url,
            timeout=config.request_timeout_s,
        )
        # Drain any pending fallback events on construction. If the daemon is
        # still down this no-ops gracefully (events get re-queued).
        if config.auto_fallback:
            self._drain_fallback()

    def send(self, event: AnyEvent) -> None:
        try:
            self._post(event)
        except (httpx.HTTPError, httpx.HTTPStatusError) as exc:
            if self._config.strict:
                raise
            logger.warning("daemon POST failed (%s); queuing to fallback", exc)
            if self._config.auto_fallback:
                fallback.append_event(self._config.fallback_path, event)

    def _post(self, event: AnyEvent) -> None:
        response = self._client.post(
            "/events",
            content=event.model_dump_json(),
            headers={"content-type": "application/json", **self._auth_headers()},
        )
        response.raise_for_status()

    def _auth_headers(self) -> dict[str, str]:
        token = self._config.auth_token
        return {"authorization": f"Bearer {token}"} if token else {}

    def _drain_fallback(self) -> None:
        try:
            replay_file = fallback.begin_replay(self._config.fallback_path)
        except (OSError, ValueError) as exc:
            logger.warning("could not prepare fallback replay: %s", exc)
            return
        if replay_file is None:
            return
        queued = list(fallback.iter_events(replay_file))
        for index, event in enumerate(queued):
            try:
                self._post(event)
            except (httpx.HTTPError, httpx.HTTPStatusError):
                # Daemon is still down. Re-append the failed event and every
                # later event from the replay batch; only earlier events were
                # confirmed accepted. The replay file is deleted after requeue,
                # so a crash during requeue prefers duplicate replay over loss.
                for remaining in queued[index:]:
                    fallback.append_event(self._config.fallback_path, remaining)
                fallback.finish_replay(replay_file)
                break
        else:
            fallback.finish_replay(replay_file)

    def close(self) -> None:
        self._client.close()


class _TeeTransport(Transport):
    """Wrap a primary transport and additionally fan each event out to
    one or more secondary emitters (OTel, OpenLineage, …).

    The primary transport's failure semantics are unchanged. Each
    emitter's ``emit()`` is called inside a ``try``/``except`` so a
    misconfigured exporter never breaks the SDK.
    """

    def __init__(self, primary: Transport, emitters: list[Any]) -> None:
        self._primary = primary
        self._emitters = list(emitters)

    @property
    def emitters(self) -> list[Any]:
        """Public for tests to inspect / monkeypatch."""
        return self._emitters

    def send(self, event: AnyEvent) -> None:
        self._primary.send(event)
        for emitter in self._emitters:
            try:
                emitter.emit(event)
            except Exception as exc:
                logger.debug(
                    "tee.emit on %s raised: %s",
                    type(emitter).__name__,
                    exc,
                )

    def close(self) -> None:
        for emitter in self._emitters:
            try:
                emitter.shutdown()
            except Exception as exc:
                logger.debug(
                    "%s shutdown raised: %s",
                    type(emitter).__name__,
                    exc,
                )
        self._primary.close()


# Backwards-compatible alias — earlier code (and tests) referenced
# ``_OTelTeeTransport`` directly.
_OTelTeeTransport = _TeeTransport


def build_transport(config: SDKConfig) -> Transport:
    """Construct the right transport for *config*.

    When ``config.otel_endpoint`` and/or ``config.openlineage_endpoint``
    is set, the primary transport is wrapped in :class:`_TeeTransport`
    fanning each event out to the configured exporter(s). Without the
    optional ``[otel]`` extra, the OTel side is a no-op and a one-time
    warning fires from :func:`hutch.otel.build_otel_exporter`.
    """
    primary: Transport
    if config.mode == "embedded":
        primary = EmbeddedTransport(config.db_path)
    else:
        primary = DaemonTransport(config)

    secondaries: list[Any] = []
    if config.otel_endpoint:
        from hutch.otel import build_otel_exporter

        otel = build_otel_exporter(
            endpoint=config.otel_endpoint,
            service_name=config.otel_service_name,
        )
        if otel is not None:
            secondaries.append(otel)
    if config.openlineage_endpoint:
        from hutch.openlineage import build_openlineage_emitter

        ol = build_openlineage_emitter(
            endpoint=config.openlineage_endpoint,
            namespace=config.openlineage_namespace,
        )
        if ol is not None:
            secondaries.append(ol)

    if secondaries:
        return _TeeTransport(primary, secondaries)
    return primary
