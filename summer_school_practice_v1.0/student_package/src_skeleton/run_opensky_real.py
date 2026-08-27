from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from m2_protocol import parse_state_vector, encode_position_message, decode_position_message
import m3_tracks as m3
from run_all import (
    DECODED_FIELDS,
    SITUATION_FIELDS,
    ROUNDTRIP_FIELDS,
    _write_csv,
    _decoded_row,
    _roundtrip,
)


STUDENT_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = STUDENT_PACKAGE_ROOT / "output"
SOURCE_DIR = STUDENT_PACKAGE_ROOT / "data" / "opensky_real" / "source"
SNAPSHOT_FILES = sorted(SOURCE_DIR.glob("*.json"))
SOURCE_LABEL = "opensky_real"

SELECTED_FIELDS = [
    "snapshot_index", "snapshot_time", "icao24", "callsign", "time_position",
    "last_contact", "longitude", "latitude", "baro_altitude", "on_ground",
    "velocity", "true_track", "vertical_rate", "geo_altitude",
]

TRANSMISSION_FIELDS = [
    "seq", "target_id", "timestamp", "message_seq", "frame_length",
    "checksum_ok", "message_valid", "validation_errors",
]


def _source_row(snap_idx: int, snap_time: int, vector: list[Any]) -> dict[str, Any]:
    return {
        "snapshot_index": snap_idx,
        "snapshot_time": snap_time,
        "icao24": vector[0],
        "callsign": vector[1],
        "time_position": vector[3],
        "last_contact": vector[4],
        "longitude": vector[5],
        "latitude": vector[6],
        "baro_altitude": vector[7],
        "on_ground": vector[8],
        "velocity": vector[9],
        "true_track": vector[10],
        "vertical_rate": vector[11],
        "geo_altitude": vector[13],
    }


def main() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)

    # 1. 读取 3 个 source JSON，合并 71 条状态
    source_vectors: list[tuple[int, int, list[Any]]] = []
    selected_rows: list[dict[str, Any]] = []
    for snap_idx, f in enumerate(SNAPSHOT_FILES, start=1):
        snap = json.load(open(f, encoding="utf-8"))
        for vector in snap["states"]:
            source_vectors.append((snap_idx, snap["time"], vector))
            selected_rows.append(_source_row(snap_idx, snap["time"], vector))
    _write_csv("selected_source_states.csv", SELECTED_FIELDS, selected_rows)

    # 2. 解析 → 编码
    frames: list[bytes] = []
    frame_records: list[dict[str, Any]] = []
    for _, _, vector in source_vectors:
        rec = parse_state_vector(vector)
        if rec["timestamp"] is None or not rec["target_id"]:
            continue
        frames.append(encode_position_message(rec, len(frames)))
        frame_records.append(rec)
    (OUTPUT_ROOT / "transmitted_frames.bin").write_bytes(b"".join(frames))

    # 3. 逐帧传输 → 解码 → 精度报告
    transmission_rows: list[dict[str, Any]] = []
    decoded_list: list[dict[str, Any]] = []
    decoded_rows: list[dict[str, Any]] = []
    precision_rows: list[dict[str, Any]] = []
    for seq, (rec, frame) in enumerate(zip(frame_records, frames)):
        decoded = decode_position_message(frame)
        decoded_list.append(decoded)
        transmission_rows.append({
            "seq": seq,
            "target_id": rec["target_id"],
            "timestamp": rec["timestamp"],
            "message_seq": seq,
            "frame_length": len(frame),
            "checksum_ok": decoded["checksum"] == decoded["expected_checksum"],
            "message_valid": decoded["message_valid"],
            "validation_errors": ";".join(decoded["validation_errors"]),
        })
        decoded_rows.append(_decoded_row(rec, decoded, SOURCE_LABEL))
        precision_rows.extend(_roundtrip(rec, decoded))

    _write_csv("transmission_log.csv", TRANSMISSION_FIELDS, transmission_rows)
    _write_csv("decoded_states.csv", DECODED_FIELDS, decoded_rows)
    _write_csv("precision_error_report.csv", ROUNDTRIP_FIELDS, precision_rows)

    # 4. 航迹与当前态势
    _write_csv("receiver_situation_initial.csv", SITUATION_FIELDS, [])
    track_rows = m3.build_tracks(decoded_list)
    situation = m3.build_current_situation(decoded_list)
    _write_csv("receiver_situation_final.csv", SITUATION_FIELDS, situation)

    # 5. SQLite 接收记录
    for r in decoded_list:
        r["source"] = SOURCE_LABEL
    m3.save_records_to_sqlite(decoded_list, str(OUTPUT_ROOT / "received_states.db"))

    # 6. 实验摘要
    summary = {
        "dataset": "OpenSky Central Europe three-snapshot teaching dataset",
        "snapshot_count": len(SNAPSHOT_FILES),
        "source_record_count": len(source_vectors),
        "encoded_frame_count": len(frames),
        "decoded_frame_count": len(decoded_list),
        "valid_frame_count": sum(1 for d in decoded_list if d["message_valid"]),
        "track_record_count": len(track_rows),
        "situation_count": len(situation),
        "precision_total": len(precision_rows),
        "precision_passed": sum(1 for p in precision_rows if p["passed"]),
    }
    (OUTPUT_ROOT / "experiment_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
