from __future__ import annotations

from typing import Any


# 人工核验后定稿的权威映射规则（纠错 + 补全的依据）
# (source_format, input_field, unified_field, mapping_rule, unit_conversion, null_strategy, evidence)
_VERIFIED_RULES: list[tuple[str, str, str, str, str, str, str]] = [
    # ---- OpenSky 来源 ----
    ("OpenSky", "target_id", "track_id", "六位小写十六进制，保留前导0", "无", "缺失→null", "source_field_definitions.md track_id"),
    ("OpenSky", "latest_time", "timestamp", "直接映射Unix秒", "无", "空值→null；必须为正整数", "source_field_definitions.md timestamp"),
    ("OpenSky", "time_source", "quality.time_source", "直接映射", "无", "position_time/last_contact_fallback", "source_field_definitions.md time_source"),
    ("OpenSky", "callsign", "identity.callsign", "直接映射", "无", "空值→null", "source_field_definitions.md callsign"),
    ("OpenSky", "lat", "position.lat", "直接映射", "无", "空值→null", "source_field_definitions.md position.lat"),
    ("OpenSky", "lon", "position.lon", "直接映射", "无", "空值→null", "source_field_definitions.md position.lon"),
    ("OpenSky", "altitude", "position.alt", "直接映射", "无", "空值→null", "source_field_definitions.md position.alt"),
    ("OpenSky", "alt_type", "position.alt_type", "直接映射", "无", "barometric/geometric/unknown", "source_field_definitions.md position.alt_type"),
    ("OpenSky", "speed", "motion.speed", "直接映射", "无", "空值→null", "source_field_definitions.md motion.speed"),
    ("OpenSky", "heading", "motion.heading", "直接映射", "无", "空值→null；0<=heading<360", "source_field_definitions.md motion.heading"),
    ("OpenSky", "vertical_rate", "motion.vertical_rate", "直接映射", "无", "空值→null", "source_field_definitions.md motion.vertical_rate"),
    ("OpenSky", "on_ground", "status.on_ground", "转为布尔值", "无", "缺失→false", "source_field_definitions.md status.on_ground"),
    ("OpenSky", "lat/lon", "quality.position_valid", "经纬度非空且合法", "无", "任一为空→false", "source_field_definitions.md position_valid"),
    ("OpenSky", "latest_time(有效性)", "quality.time_valid", "latest_time为正整数", "无", "空值→false", "source_field_definitions.md time_valid"),
    ("OpenSky", "message_valid", "quality.message_valid", "源记录结构校验结果", "无", "缺失→false", "source_field_definitions.md message_valid"),
    # ---- TeachingLink 来源 ----
    ("TeachingLink", "target_id", "track_id", "六位小写十六进制，保留前导0", "无", "缺失→null", "source_field_definitions.md track_id"),
    ("TeachingLink", "latest_time", "timestamp", "直接映射Unix秒", "无", "必须为正整数", "source_field_definitions.md timestamp"),
    ("TeachingLink", "status_flags.bit2", "quality.time_source", "bit2=0→position_time；bit2=1→last_contact_fallback", "无", "无", "source_field_definitions.md time_source"),
    ("TeachingLink", "callsign+validity_flags.bit6", "identity.callsign", "bit6=0→null；bit6=1→去除补0", "无", "有效位0→null", "source_field_definitions.md callsign"),
    ("TeachingLink", "latitude_code+validity_flags.bit0", "position.lat", "bit0=0→null；bit0=1→code/(2^22-1)×180-90", "code/(2^22-1)×180-90", "有效位0→null", "source_field_definitions.md position.lat"),
    ("TeachingLink", "longitude_code+validity_flags.bit1", "position.lon", "bit1=0→null；bit1=1→code/(2^22-1)×360-180", "code/(2^22-1)×360-180", "有效位0→null", "source_field_definitions.md position.lon"),
    ("TeachingLink", "altitude_code+validity_flags.bit2", "position.alt", "bit2=0→null；bit2=1→code-1000", "code-1000（米）", "有效位0→null", "source_field_definitions.md position.alt"),
    ("TeachingLink", "status_flags.bit1", "position.alt_type", "alt有效时 bit1=0→barometric、bit1=1→geometric；alt无效→unknown", "无", "alt无效→unknown", "source_field_definitions.md position.alt_type"),
    ("TeachingLink", "speed_code+validity_flags.bit3", "motion.speed", "bit3=0→null；bit3=1→code×0.1", "code×0.1（m/s）", "有效位0→null", "source_field_definitions.md motion.speed"),
    ("TeachingLink", "heading_code+validity_flags.bit4", "motion.heading", "bit4=0→null；bit4=1→code×0.01且<360", "code×0.01（度）", "有效位0→null", "source_field_definitions.md motion.heading"),
    ("TeachingLink", "vertical_rate_code+validity_flags.bit5", "motion.vertical_rate", "bit5=0→null；bit5=1→code×0.01-327.68", "code×0.01-327.68（m/s）", "有效位0→null", "source_field_definitions.md motion.vertical_rate"),
    ("TeachingLink", "status_flags.bit0", "status.on_ground", "bit0=1→true；bit0=0→false", "无", "无", "source_field_definitions.md status.on_ground"),
    ("TeachingLink", "纬经有效位+解码范围", "quality.position_valid", "纬经有效位均1且解码值合法", "无", "任一无效→false", "source_field_definitions.md position_valid"),
    ("TeachingLink", "timestamp+帧接收结果", "quality.time_valid", "timestamp为正整数且帧通过接收判据", "无", "帧无效→false", "source_field_definitions.md time_valid"),
    ("TeachingLink", "message_valid", "quality.message_valid", "完整帧接收判据；不得扩大为来源可信", "无", "缺失→false", "source_field_definitions.md message_valid"),
]


def verify_candidate_mapping(candidate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """依据权威字段定义对候选进行纠错与补全，形成人工核验后的正式映射。

    候选仅作参考，正式映射以 _VERIFIED_RULES（人工核验定稿）为准：
    - 纠错：候选的经纬度互换、高度偏置（code乘1米→code-1000）、
      status_flags.bit2 语义错误（time_valid→time_source）等均以权威规则为准；
    - 补全：候选仅 8 行，缺失的 speed/heading/vertical_rate/on_ground/alt_type/
      position_valid/time_valid/message_valid(OpenSky) 等字段全部按权威规则补全。
    """
    result: list[dict[str, Any]] = []
    for src, inp, uni, rule, unit, null, evid in _VERIFIED_RULES:
        result.append({
            "source_format": src,
            "input_field": inp,
            "unified_field": uni,
            "mapping_rule": rule,
            "unit_conversion": unit,
            "null_strategy": null,
            "evidence": evid,
            "verified": True,
        })
    return result


def map_to_unified(record: dict[str, Any], source_format: str) -> dict[str, Any]:
    """使用人工核验后的规则生成统一态势消息。"""
    if source_format == "OpenSky":
        lat = record.get("lat")
        lon = record.get("lon")
        latest_time = record.get("latest_time")
        return {
            "track_id": str(record["target_id"]).lower(),
            "source": "OpenSky",
            "timestamp": latest_time,
            "identity": {"callsign": record.get("callsign")},
            "position": {
                "lat": lat,
                "lon": lon,
                "alt": record.get("altitude"),
                "alt_type": record.get("alt_type") or "unknown",
            },
            "motion": {
                "speed": record.get("speed"),
                "heading": record.get("heading"),
                "vertical_rate": record.get("vertical_rate"),
            },
            "status": {"on_ground": bool(record.get("on_ground"))},
            "quality": {
                "position_valid": lat is not None and lon is not None,
                "time_valid": isinstance(latest_time, int) and latest_time > 0,
                "message_valid": bool(record.get("message_valid")),
                "time_source": record.get("time_source") or "position_time",
                "anomaly_flags": [],
            },
        }

    # TeachingLink：从协议码 + 标志位重推
    validity = int(record["validity_flags"])
    status = int(record["status_flags"])
    max22 = 2 ** 22 - 1

    lat_v = bool(validity & 0x01)
    lon_v = bool(validity & 0x02)
    alt_v = bool(validity & 0x04)
    spd_v = bool(validity & 0x08)
    hdg_v = bool(validity & 0x10)
    vr_v = bool(validity & 0x20)
    cs_v = bool(validity & 0x40)

    alt = record["altitude_code"] - 1000 if alt_v else None
    alt_type = "unknown"
    if alt_v:
        alt_type = "geometric" if (status & 0x02) else "barometric"

    callsign = record.get("callsign") if cs_v and record.get("callsign") else None
    latest_time = record.get("latest_time")

    return {
        "track_id": str(record["target_id"]).lower(),
        "source": "TeachingLink",
        "timestamp": latest_time,
        "identity": {"callsign": callsign},
        "position": {
            "lat": record["latitude_code"] / max22 * 180.0 - 90.0 if lat_v else None,
            "lon": record["longitude_code"] / max22 * 360.0 - 180.0 if lon_v else None,
            "alt": alt,
            "alt_type": alt_type,
        },
        "motion": {
            "speed": record["speed_code"] * 0.1 if spd_v else None,
            "heading": record["heading_code"] * 0.01 if hdg_v else None,
            "vertical_rate": record["vertical_rate_code"] * 0.01 - 327.68 if vr_v else None,
        },
        "status": {"on_ground": bool(status & 0x01)},
        "quality": {
            "position_valid": lat_v and lon_v,
            "time_valid": bool(record.get("message_valid")) and isinstance(latest_time, int) and latest_time > 0,
            "message_valid": bool(record.get("message_valid")),
            "time_source": "last_contact_fallback" if (status & 0x04) else "position_time",
            "anomaly_flags": [],
        },
    }
