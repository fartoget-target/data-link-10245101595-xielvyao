from __future__ import annotations

from typing import Any

from pathlib import Path

from m2_protocol import decode_position_message

import sqlite3

SCHEMA_PATH = Path(__file__).resolve().parents[1]/"schema" / "optional_db_schema.sql"


def _acceptable(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """仅保留可接受记录：message_valid=True 且 target_id、timestamp 可用。"""
    return [
        r for r in records
        if r.get("message_valid") and r.get("target_id") and r.get("timestamp") is not None
    ]


def decode_message_stream(data: bytes, frame_size: int = 41) -> list[dict[str, Any]]:
    """按固定帧长批量解码；记录并忽略不完整尾帧。"""
    records = []
    full_frames = len(data) // frame_size

    has_tail = bool(len(data) % frame_size)

    for i in range(full_frames):
        frame = data[i * frame_size:(i+1) * frame_size]
        decode = decode_position_message(frame)
        records.append(decode)

    # 尾部残余字节：记录 LENGTH_ERROR，忽略不完整尾帧
    if has_tail:
        records.append({
            "target_id": None, "message_valid": False,
            "validation_errors": ["LENGTH_ERROR"],
        })

    return records


def save_records_to_sqlite(records: list[dict[str, Any]], db_path: str) -> None:
    """选做：保存接收记录，None必须写为NULL。"""
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS state_record")   # 先删旧表，保证可重复运行
    cur.execute(SCHEMA_PATH.read_text(encoding="utf-8"))

    records = _acceptable(records)

    columns = ["target_id", "callsign", "timestamp", "timestamp_source", "message_seq", "lat", "lon", "altitude", "alt_type", "speed", "heading", "vertical_rate", "on_ground", "status_flags", "validity_flags", "message_valid", "source"]
    placeholders = ",".join("?" * len(columns))  #占位符，防注入，自动处理None

    for r in records:
        values = (
            r.get("target_id"),
            r.get("callsign"),
            r.get("timestamp"),
            r.get("timestamp_source",r.get("time_source")),
            r.get("message_seq"),
            r.get("lat"),
            r.get("lon"),
            r.get("altitude"),
            r.get("alt_type"),
            r.get("speed"),
            r.get("heading"),
            r.get("vertical_rate"),
            int(r.get("on_ground", False)),     #将bool类型转换为sql数据库可使用的0，1
            r.get("status_flags"),
            r.get("validity_flags"),
            int(r.get("message_valid", False)),
            r.get("source", ""),
        )
        cur.execute(f"INSERT INTO state_record({','.join(columns)})" f"VALUES ({placeholders})", values)

    conn.commit()

    cur.execute("SELECT target_id, timestamp, lat, lon, callsign FROM state_record")
    rows = cur.fetchall()

    cur.execute("SELECT target_id, COUNT(*) FROM state_record GROUP BY target_id")
    counts = cur.fetchall()

    # 写入与重读一致性验证
    assert len(rows) == len(records), f"写入 {len(records)} 条，重读 {len(rows)} 条，不一致"
    conn.close()


def build_tracks(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """仅使用可接受记录，按target_id分组并按timestamp排序。"""
    groups: dict[str, list[dict[str, Any]]] = {}
    for r in _acceptable(records):
        groups.setdefault(r["target_id"], []).append(r)

    rows: list[dict[str, Any]] = []
    for tid, grp in groups.items():
        grp.sort(key=lambda r: r["timestamp"])
        for seq, r in enumerate(grp, start=1):
            rows.append({
                "target_id": r["target_id"],
                "timestamp": r["timestamp"],
                "message_seq": r["message_seq"],
                "track_sequence_no": seq,
                "lat": r["lat"],
                "lon": r["lon"],
                "altitude": r["altitude"],
                "speed": r["speed"],
                "heading": r["heading"],
            })
    return rows

    

def build_current_situation(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """每个目标保留时间最新的可接受记录；可选字段缺失仍可入选。"""
    acc = _acceptable(records)

    latest: dict[str, dict[str, Any]] = {}
    track_length: dict[str, int] = {}

    for r in acc:
        tid = r["target_id"]
        track_length[tid] = track_length.get(tid, 0) + 1
        if tid not in latest or r["timestamp"] > latest[tid]["timestamp"]:
            latest[tid] = r
    
    rows: list[dict[str, Any]] = []
    for tid, r in latest.items():
        rows.append({
            "target_id": tid,
            "callsign": r["callsign"],
            "latest_time": r["timestamp"],
            "lat": r["lat"],
            "lon": r["lon"],
            "altitude": r["altitude"],
            "speed": r["speed"],
            "heading": r["heading"],
            "vertical_rate": r["vertical_rate"],
            "on_ground": r["on_ground"],
            "track_length": track_length[tid],
            "alt_type": r["alt_type"],
            "time_source": r["time_source"],
            "message_valid": r["message_valid"],
        })

    return rows
