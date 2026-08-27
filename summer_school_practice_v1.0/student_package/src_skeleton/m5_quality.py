from __future__ import annotations

from typing import Any


BATCH_TIME = 1710000120


def check_record(record: dict[str, Any], batch_time: int = BATCH_TIME) -> list[dict[str, Any]]:
    """检查位置缺失、时间延迟和航向越界。"""
    alerts: list[dict[str, Any]] = []
    tid = record.get("target_id")

    # R1：位置缺失（lat 或 lon 为空）→ HIGH
    if record.get("lat") is None or record.get("lon") is None:
        field = "lat" if record.get("lat") is None else "lon"
        alerts.append({
            "alert_time": batch_time,
            "target_id": tid,
            "alert_type": "POSITION_MISSING",
            "severity": "HIGH",
            "field": field,
            "description": "纬度或经度缺失",
        })

    # R2：数据延迟（batch_time - record_time > 60）→ MEDIUM
    record_time = record.get("timestamp")
    if record_time is None:
        record_time = record.get("latest_time")
    if record_time is not None and (batch_time - record_time) > 60:
        alerts.append({
            "alert_time": batch_time,
            "target_id": tid,
            "alert_type": "DATA_DELAYED",
            "severity": "MEDIUM",
            "field": "timestamp",
            "description": "数据延迟超过60秒",
        })

    # R4：航向越界（heading 非空且 <0 或 >=360）→ MEDIUM；heading 为空不触发
    heading = record.get("heading")
    if heading is not None and (heading < 0 or heading >= 360):
        alerts.append({
            "alert_time": batch_time,
            "target_id": tid,
            "alert_type": "HEADING_OUT_OF_RANGE",
            "severity": "MEDIUM",
            "field": "heading",
            "description": "航向越界(需0<=heading<360)",
        })

    return alerts


def check_duplicates(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """使用target_id+timestamp联合键检查重复。"""
    alerts: list[dict[str, Any]] = []
    seen: set[tuple[Any, Any]] = set()
    for r in records:
        key = (r.get("target_id"), r.get("timestamp"))
        if key in seen:
            alerts.append({
                "alert_time": BATCH_TIME,
                "target_id": r.get("target_id"),
                "alert_type": "DUPLICATE_RECORD",
                "severity": "MEDIUM",
                "field": "timestamp",
                "description": "target_id与timestamp均重复",
            })
        else:
            seen.add(key)
    return alerts


def build_quality_situation(records: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """按HIGH > MEDIUM > NONE合成质量态势。

    布尔标志与异常等级均从 records 直接重推（与 check_record/check_duplicates 一致），
    alerts 参数仅保留以符合接口；重复对的第 2 次及以后标记 duplicate_detected。
    """
    # 统计 (target_id, timestamp) 出现次数，用于判断重复
    key_count: dict[tuple[Any, Any], int] = {}
    for r in records:
        key = (r.get("target_id"), r.get("timestamp"))
        key_count[key] = key_count.get(key, 0) + 1

    rows: list[dict[str, Any]] = []
    seen_key: set[tuple[Any, Any]] = set()
    for r in records:
        tid = r.get("target_id")
        ts = r.get("timestamp")
        record_time = ts if ts is not None else r.get("latest_time")

        position_valid = r.get("lat") is not None and r.get("lon") is not None
        delayed = record_time is not None and (BATCH_TIME - record_time) > 60
        heading = r.get("heading")
        heading_valid = heading is not None and 0 <= heading < 360

        key = (tid, ts)
        duplicate_detected = key_count.get(key, 0) > 1 and key in seen_key
        seen_key.add(key)

        if not position_valid:
            anomaly_level = "HIGH"
        elif delayed or duplicate_detected or not heading_valid:
            anomaly_level = "MEDIUM"
        else:
            anomaly_level = "NONE"
        display_status = {"HIGH": "ERROR", "MEDIUM": "WARNING", "NONE": "NORMAL"}[anomaly_level]

        rows.append({
            "target_id": tid,
            "timestamp": ts,
            "position_valid": position_valid,
            "delayed": delayed,
            "duplicate_detected": duplicate_detected,
            "heading_valid": heading_valid,
            "message_valid": r.get("message_valid"),
            "anomaly_level": anomaly_level,
            "display_status": display_status,
        })

    return rows
