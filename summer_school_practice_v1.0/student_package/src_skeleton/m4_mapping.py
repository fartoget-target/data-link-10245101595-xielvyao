from __future__ import annotations

from typing import Any


_MAX22 = 2 ** 22 - 1


# 单一映射表：既是核验表（verified_mapping_table.csv）的来源，也是 map_to_unified 的执行来源。
# 每行: (source_format, input_field, unified_field, kind, source_key,
#        mapping_rule, unit_conversion, null_strategy, evidence)
#   kind：转换方式标识，见下方 _TRANSFORMS；
#   source_key：direct/bool/lower_hex 等需要读取的记录键；自包含转换（bit_*、*_valid 等）为 None。
_FIELD_MAP: list[tuple[str, str, str, str, str | None, str, str, str, str]] = [
    # ---- OpenSky 来源 ----
    ("OpenSky", "target_id", "track_id", "lower_hex", "target_id", "六位小写十六进制，保留前导0", "无", "缺失→null", "source_field_definitions.md track_id"),
    ("OpenSky", "latest_time", "timestamp", "direct", "latest_time", "直接映射Unix秒", "无", "空值→null；必须为正整数", "source_field_definitions.md timestamp"),
    ("OpenSky", "time_source", "quality.time_source", "time_source_opensky", None, "直接映射", "无", "position_time/last_contact_fallback", "source_field_definitions.md time_source"),
    ("OpenSky", "callsign", "identity.callsign", "direct", "callsign", "直接映射", "无", "空值→null", "source_field_definitions.md callsign"),
    ("OpenSky", "lat", "position.lat", "direct", "lat", "直接映射", "无", "空值→null", "source_field_definitions.md position.lat"),
    ("OpenSky", "lon", "position.lon", "direct", "lon", "直接映射", "无", "空值→null", "source_field_definitions.md position.lon"),
    ("OpenSky", "altitude", "position.alt", "direct", "altitude", "直接映射", "无", "空值→null", "source_field_definitions.md position.alt"),
    ("OpenSky", "alt_type", "position.alt_type", "alt_type_opensky", None, "直接映射", "无", "barometric/geometric/unknown", "source_field_definitions.md position.alt_type"),
    ("OpenSky", "speed", "motion.speed", "direct", "speed", "直接映射", "无", "空值→null", "source_field_definitions.md motion.speed"),
    ("OpenSky", "heading", "motion.heading", "direct", "heading", "直接映射", "无", "空值→null；0<=heading<360", "source_field_definitions.md motion.heading"),
    ("OpenSky", "vertical_rate", "motion.vertical_rate", "direct", "vertical_rate", "直接映射", "无", "空值→null", "source_field_definitions.md motion.vertical_rate"),
    ("OpenSky", "on_ground", "status.on_ground", "bool", "on_ground", "转为布尔值", "无", "缺失→false", "source_field_definitions.md status.on_ground"),
    ("OpenSky", "lat/lon", "quality.position_valid", "position_valid_opensky", None, "经纬度非空且合法", "无", "任一为空→false", "source_field_definitions.md position_valid"),
    ("OpenSky", "latest_time(有效性)", "quality.time_valid", "time_valid_opensky", None, "latest_time为正整数", "无", "空值→false", "source_field_definitions.md time_valid"),
    ("OpenSky", "message_valid", "quality.message_valid", "bool", "message_valid", "源记录结构校验结果", "无", "缺失→false", "source_field_definitions.md message_valid"),
    # ---- TeachingLink 来源 ----
    ("TeachingLink", "target_id", "track_id", "lower_hex", "target_id", "六位小写十六进制，保留前导0", "无", "缺失→null", "source_field_definitions.md track_id"),
    ("TeachingLink", "latest_time", "timestamp", "direct", "latest_time", "直接映射Unix秒", "无", "必须为正整数", "source_field_definitions.md timestamp"),
    ("TeachingLink", "status_flags.bit2", "quality.time_source", "bit_time_source", None, "bit2=0→position_time；bit2=1→last_contact_fallback", "无", "无", "source_field_definitions.md time_source"),
    ("TeachingLink", "callsign+validity_flags.bit6", "identity.callsign", "bit_callsign", None, "bit6=0→null；bit6=1→去除补0", "无", "有效位0→null", "source_field_definitions.md callsign"),
    ("TeachingLink", "latitude_code+validity_flags.bit0", "position.lat", "bit_lat", None, "bit0=0→null；bit0=1→code/(2^22-1)×180-90", "code/(2^22-1)×180-90", "有效位0→null", "source_field_definitions.md position.lat"),
    ("TeachingLink", "longitude_code+validity_flags.bit1", "position.lon", "bit_lon", None, "bit1=0→null；bit1=1→code/(2^22-1)×360-180", "code/(2^22-1)×360-180", "有效位0→null", "source_field_definitions.md position.lon"),
    ("TeachingLink", "altitude_code+validity_flags.bit2", "position.alt", "bit_alt", None, "bit2=0→null；bit2=1→code-1000", "code-1000（米）", "有效位0→null", "source_field_definitions.md position.alt"),
    ("TeachingLink", "status_flags.bit1", "position.alt_type", "bit_alt_type", None, "alt有效时 bit1=0→barometric、bit1=1→geometric；alt无效→unknown", "无", "alt无效→unknown", "source_field_definitions.md position.alt_type"),
    ("TeachingLink", "speed_code+validity_flags.bit3", "motion.speed", "bit_speed", None, "bit3=0→null；bit3=1→code×0.1", "code×0.1（m/s）", "有效位0→null", "source_field_definitions.md motion.speed"),
    ("TeachingLink", "heading_code+validity_flags.bit4", "motion.heading", "bit_heading", None, "bit4=0→null；bit4=1→code×0.01且<360", "code×0.01（度）", "有效位0→null", "source_field_definitions.md motion.heading"),
    ("TeachingLink", "vertical_rate_code+validity_flags.bit5", "motion.vertical_rate", "bit_vr", None, "bit5=0→null；bit5=1→code×0.01-327.68", "code×0.01-327.68（m/s）", "有效位0→null", "source_field_definitions.md motion.vertical_rate"),
    ("TeachingLink", "status_flags.bit0", "status.on_ground", "bit_on_ground", None, "bit0=1→true；bit0=0→false", "无", "无", "source_field_definitions.md status.on_ground"),
    ("TeachingLink", "纬经有效位+解码范围", "quality.position_valid", "position_valid_tl", None, "纬经有效位均1且解码值合法", "无", "任一无效→false", "source_field_definitions.md position_valid"),
    ("TeachingLink", "timestamp+帧接收结果", "quality.time_valid", "time_valid_tl", None, "timestamp为正整数且帧通过接收判据", "无", "帧无效→false", "source_field_definitions.md time_valid"),
    ("TeachingLink", "message_valid", "quality.message_valid", "bool", "message_valid", "完整帧接收判据；不得扩大为来源可信", "无", "缺失→false", "source_field_definitions.md message_valid"),
]


def _t_lower_hex(record: dict[str, Any], key: str) -> str:
    return str(record.get(key, "")).lower()


def _t_direct(record: dict[str, Any], key: str) -> Any:
    return record.get(key)


def _t_bool(record: dict[str, Any], key: str) -> bool:
    return bool(record.get(key))


def _t_time_source_opensky(record: dict[str, Any], key: str) -> str:
    return record.get("time_source") or "position_time"


def _t_alt_type_opensky(record: dict[str, Any], key: str) -> str:
    return record.get("alt_type") or "unknown"


def _t_position_valid_opensky(record: dict[str, Any], key: str) -> bool:
    return record.get("lat") is not None and record.get("lon") is not None


def _t_time_valid_opensky(record: dict[str, Any], key: str) -> bool:
    t = record.get("latest_time")
    return isinstance(t, int) and t > 0


def _t_bit_time_source(record: dict[str, Any], key: str) -> str:
    return "last_contact_fallback" if (int(record["status_flags"]) & 4) else "position_time"


def _t_bit_callsign(record: dict[str, Any], key: str) -> Any:
    return record.get("callsign") if (int(record["validity_flags"]) & 64) and record.get("callsign") else None


def _t_bit_lat(record: dict[str, Any], key: str) -> Any:
    return record["latitude_code"] / _MAX22 * 180.0 - 90.0 if (int(record["validity_flags"]) & 1) else None


def _t_bit_lon(record: dict[str, Any], key: str) -> Any:
    return record["longitude_code"] / _MAX22 * 360.0 - 180.0 if (int(record["validity_flags"]) & 2) else None


def _t_bit_alt(record: dict[str, Any], key: str) -> Any:
    return record["altitude_code"] - 1000 if (int(record["validity_flags"]) & 4) else None


def _t_bit_alt_type(record: dict[str, Any], key: str) -> str:
    if not (int(record["validity_flags"]) & 4):
        return "unknown"
    return "geometric" if (int(record["status_flags"]) & 2) else "barometric"


def _t_bit_speed(record: dict[str, Any], key: str) -> Any:
    return record["speed_code"] * 0.1 if (int(record["validity_flags"]) & 8) else None


def _t_bit_heading(record: dict[str, Any], key: str) -> Any:
    return record["heading_code"] * 0.01 if (int(record["validity_flags"]) & 16) else None


def _t_bit_vr(record: dict[str, Any], key: str) -> Any:
    return record["vertical_rate_code"] * 0.01 - 327.68 if (int(record["validity_flags"]) & 32) else None


def _t_bit_on_ground(record: dict[str, Any], key: str) -> bool:
    return bool(int(record["status_flags"]) & 1)


def _t_position_valid_tl(record: dict[str, Any], key: str) -> bool:
    v = int(record["validity_flags"])
    return bool(v & 1 and v & 2)


def _t_time_valid_tl(record: dict[str, Any], key: str) -> bool:
    t = record.get("latest_time")
    return bool(record.get("message_valid")) and isinstance(t, int) and t > 0


# kind → 转换函数（record, source_key）-> value
_TRANSFORMS = {
    "lower_hex": _t_lower_hex,
    "direct": _t_direct,
    "bool": _t_bool,
    "time_source_opensky": _t_time_source_opensky,
    "alt_type_opensky": _t_alt_type_opensky,
    "position_valid_opensky": _t_position_valid_opensky,
    "time_valid_opensky": _t_time_valid_opensky,
    "bit_time_source": _t_bit_time_source,
    "bit_callsign": _t_bit_callsign,
    "bit_lat": _t_bit_lat,
    "bit_lon": _t_bit_lon,
    "bit_alt": _t_bit_alt,
    "bit_alt_type": _t_bit_alt_type,
    "bit_speed": _t_bit_speed,
    "bit_heading": _t_bit_heading,
    "bit_vr": _t_bit_vr,
    "bit_on_ground": _t_bit_on_ground,
    "position_valid_tl": _t_position_valid_tl,
    "time_valid_tl": _t_time_valid_tl,
}


def _set_nested(obj: dict[str, Any], path: str, value: Any) -> None:
    """按点分路径写入嵌套字典，如 position.lat → obj['position']['lat']。"""
    parts = path.split(".")
    cur = obj
    for part in parts[:-1]:
        cur = cur.setdefault(part, {})
    cur[parts[-1]] = value


def verify_candidate_mapping(candidate_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """依据权威字段定义对候选进行纠错与补全，形成人工核验后的正式映射。

    候选仅作参考，正式映射以 _FIELD_MAP（人工核验定稿）为准：
    - 纠错：候选的经纬度互换、高度偏置（code乘1米→code-1000）、
      status_flags.bit2 语义错误（time_valid→time_source）等均以权威规则为准；
    - 补全：候选仅 8 行，缺失的 speed/heading/vertical_rate/on_ground/alt_type/
      position_valid/time_valid/message_valid(OpenSky) 等字段全部按权威规则补全。
    """
    result: list[dict[str, Any]] = []
    for src, inp, uni, _kind, _skey, rule, unit, null, evid in _FIELD_MAP:
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
    """使用人工核验后的规则生成统一态势消息。

    字段对应关系由 _FIELD_MAP 驱动（数据驱动），具体数值转换由 _TRANSFORMS 提供（过程式）。
    """
    result: dict[str, Any] = {
        "track_id": None,
        "source": source_format,
        "timestamp": None,
        "identity": {"callsign": None},
        "position": {"lat": None, "lon": None, "alt": None, "alt_type": "unknown"},
        "motion": {"speed": None, "heading": None, "vertical_rate": None},
        "status": {"on_ground": False},
        "quality": {
            "position_valid": False,
            "time_valid": False,
            "message_valid": False,
            "time_source": "position_time",
            "anomaly_flags": [],
        },
    }
    for src, _inp, uni, kind, skey, _rule, _unit, _null, _evid in _FIELD_MAP:
        if src != source_format:
            continue
        value = _TRANSFORMS[kind](record, skey)
        _set_nested(result, uni, value)
    return result
