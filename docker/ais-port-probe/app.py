import asyncio
import json
import os
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import websockets


DEFAULT_PORTS = {
    "Port of Santos": [[-24.15, -46.45], [-23.90, -46.25]],
    "Port of Rio de Janeiro": [[-23.05, -43.35], [-22.75, -43.00]],
    "Port of Paranagua": [[-25.65, -48.65], [-25.40, -48.35]],
}

NAV_STATUS = {
    0: "under_way",
    1: "at_anchor",
    5: "moored",
}


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_ports(raw_ports: Any) -> dict[str, list[list[float]]]:
    if not isinstance(raw_ports, dict) or not raw_ports:
        return DEFAULT_PORTS

    normalized: dict[str, list[list[float]]] = {}
    for port_name, box in raw_ports.items():
        if not isinstance(port_name, str):
            continue
        if not isinstance(box, list) or len(box) != 2:
            continue
        first, second = box
        if not isinstance(first, list) or not isinstance(second, list):
            continue
        if len(first) != 2 or len(second) != 2:
            continue
        try:
            normalized[port_name] = [
                [float(first[0]), float(first[1])],
                [float(second[0]), float(second[1])],
            ]
        except (TypeError, ValueError):
            continue

    return normalized or DEFAULT_PORTS


def get_port_zone(lat: float, lon: float, ports: dict[str, list[list[float]]]) -> str | None:
    for port_name, box in ports.items():
        lat_min = min(box[0][0], box[1][0])
        lat_max = max(box[0][0], box[1][0])
        lon_min = min(box[0][1], box[1][1])
        lon_max = max(box[0][1], box[1][1])
        if lat_min <= lat <= lat_max and lon_min <= lon <= lon_max:
            return port_name
    return None


def is_waiting(status_code: int | None, sog: float | None) -> bool:
    return status_code == 1 or (sog is not None and sog < 0.5)


async def collect_snapshot(
    api_key: str,
    ports: dict[str, list[list[float]]],
    listen_time_seconds: int,
) -> dict[str, Any]:
    started_at = now_iso()
    start_monotonic = time.monotonic()
    deadline = start_monotonic + listen_time_seconds
    tracked_vessels: dict[str, dict[str, Any]] = {}
    raw_messages_received = 0
    position_reports_received = 0
    port_reports_received = 0
    errors: list[str] = []

    async with websockets.connect(
        "wss://stream.aisstream.io/v0/stream",
        open_timeout=10,
        close_timeout=5,
        ping_interval=20,
        ping_timeout=20,
        max_size=None,
    ) as websocket:
        subscribe_message = {
            "APIKey": api_key,
            "BoundingBoxes": list(ports.values()),
            "FilterMessageTypes": ["PositionReport"],
        }
        await websocket.send(json.dumps(subscribe_message))

        while time.monotonic() < deadline:
            timeout = min(1.0, max(0.0, deadline - time.monotonic()))
            if timeout <= 0:
                break
            try:
                message_json = await asyncio.wait_for(websocket.recv(), timeout=timeout)
            except asyncio.TimeoutError:
                continue

            raw_messages_received += 1

            try:
                message = json.loads(message_json)
            except json.JSONDecodeError:
                errors.append("invalid_json_message")
                continue

            if message.get("MessageType") != "PositionReport":
                continue

            position_reports_received += 1
            data = message.get("Message", {}).get("PositionReport", {})

            try:
                lat = float(data.get("Latitude"))
                lon = float(data.get("Longitude"))
            except (TypeError, ValueError):
                continue

            port_name = get_port_zone(lat, lon, ports)
            if not port_name:
                continue

            port_reports_received += 1

            try:
                sog = float(data.get("Sog", 0))
            except (TypeError, ValueError):
                sog = 0.0

            try:
                status_code = int(data.get("NavigationalStatus", 99))
            except (TypeError, ValueError):
                status_code = 99

            if not is_waiting(status_code, sog):
                continue

            mmsi = str(data.get("UserID") or "")
            if not mmsi:
                continue

            vessel = tracked_vessels.get(mmsi)
            seen_at = now_iso()
            payload = {
                "mmsi": mmsi,
                "port_name": port_name,
                "status_code": status_code,
                "status_label": NAV_STATUS.get(status_code, f"other_{status_code}"),
                "sog": round(sog, 4),
                "latitude": round(lat, 6),
                "longitude": round(lon, 6),
                "first_seen_at": seen_at if vessel is None else vessel["first_seen_at"],
                "last_seen_at": seen_at,
            }
            tracked_vessels[mmsi] = payload

    ports_summary = []
    total_anchored_vessels = 0
    for port_name in ports.keys():
        vessels = [v for v in tracked_vessels.values() if v["port_name"] == port_name]
        anchored_count = len(vessels)
        total_anchored_vessels += anchored_count
        ports_summary.append(
            {
                "port_name": port_name,
                "anchored_vessels_count": anchored_count,
                "average_sog": round(sum(v["sog"] for v in vessels) / anchored_count, 4) if anchored_count else 0.0,
                "vessels": vessels,
            }
        )

    top_congested_port = max(
        ports_summary,
        key=lambda port: port["anchored_vessels_count"],
        default=None,
    )

    return {
        "source": "AISSTREAM_PORT_CONGESTION",
        "status": "done",
        "started_at": started_at,
        "completed_at": now_iso(),
        "snapshot_seconds": listen_time_seconds,
        "ports": ports_summary,
        "port_names": list(ports.keys()),
        "ports_monitored": len(ports_summary),
        "raw_messages_received": raw_messages_received,
        "position_reports_received": position_reports_received,
        "port_reports_received": port_reports_received,
        "total_anchored_vessels": total_anchored_vessels,
        "top_congested_port": top_congested_port,
        "errors": errors,
    }


class PortSnapshotHandler(BaseHTTPRequestHandler):
    server_version = "AISPortProbe/1.0"

    def _send_json(self, status_code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/health":
            self._send_json(200, {"status": "ok", "service": "ais-port-probe", "time": now_iso()})
            return
        self._send_json(404, {"status": "error", "message": "not_found"})

    def do_POST(self) -> None:
        if self.path != "/snapshot":
            self._send_json(404, {"status": "error", "message": "not_found"})
            return

        api_key = os.environ.get("AISSTREAM_API_KEY", "").strip()
        if not api_key:
            self._send_json(500, {"status": "error", "message": "missing_AISSTREAM_API_KEY"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length) if content_length > 0 else b"{}"
        try:
            body = json.loads(raw_body.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            self._send_json(400, {"status": "error", "message": "invalid_json_body"})
            return

        ports = normalize_ports(body.get("ports"))
        try:
            listen_time_seconds = int(body.get("listen_time_seconds", 15))
        except (TypeError, ValueError):
            listen_time_seconds = 15
        listen_time_seconds = max(5, min(60, listen_time_seconds))

        try:
            payload = asyncio.run(collect_snapshot(api_key, ports, listen_time_seconds))
        except Exception as exc:
            self._send_json(
                502,
                {
                    "status": "error",
                    "message": "snapshot_failed",
                    "error": str(exc),
                    "time": now_iso(),
                },
            )
            return

        self._send_json(200, payload)

    def log_message(self, format: str, *args: Any) -> None:
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), PortSnapshotHandler)
    print(f"AIS port probe listening on 0.0.0.0:{port}")
    server.serve_forever()
