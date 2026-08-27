from __future__ import annotations

from typing import Any

import math


FRAME_SIZE = 41

PROBLEM_TYPES = {
    "MISSING", "REQUIRED_FIELD_MISSING", "OUT_OF_RANGE", "TYPE_ERROR",
    "ENCODING_ERROR", "LENGTH_ERROR", "MAGIC_ERROR", "VERSION_ERROR",
    "MESSAGE_TYPE_ERROR", "RESERVED_BITS_ERROR", "FLAG_VALUE_INCONSISTENCY", "CHECKSUM_ERROR",
}


def parse_state_vector(vector: list[Any]) -> dict[str, Any]:
    """将OpenSky状态向量转换为发送方内部结构化记录。"""

    # 安全取下标：越界视为 None
    def get(i: int) -> Any:
        if i < len(vector):
            return vector[i]
        return None

    # 错误处理：收集本条的 validation_log 错误
    errors: list[dict[str, Any]] = []

    def add_error(field: str, problem_type: str, value: Any, description: str) -> None:
        errors.append({
            "stage": "parse",
            "field": field,
            "problem_type": problem_type,
            "value": value,
            "description": description,
        })

    # 标识索引：target_id（六位十六进制，索引0）
    target_id = get(0)
    hex_chars = set("0123456789abcdefABCDEF")  # 十六进制字符集，用于快速判断
    if target_id is None:
        target_id = ""
        add_error("icao24", "REQUIRED_FIELD_MISSING", None, "target_id缺失")
    elif not isinstance(target_id, str) or len(target_id) != 6 \
            or any(c not in hex_chars for c in target_id):
        add_error("icao24", "TYPE_ERROR", target_id, "target_id必须是6位十六进制字符串")

    # 地面状态的索引：on_ground（布尔，索引8）
    on_ground = get(8)
    if not isinstance(on_ground, bool):
        add_error("on_ground", "TYPE_ERROR", on_ground, "on_ground必须是布尔值")
        on_ground = False

    # 状态时间索引：优先 time_position（索引3），回退 last_contact（索引4）
    time_position = get(3)
    last_contact = get(4)
    if time_position is not None:
        timestamp: Any = time_position
        timestamp_source: Any = "position_time"
    elif last_contact is not None:
        timestamp: Any = last_contact
        timestamp_source: Any = "last_contact_fallback"
    else:
        timestamp = None
        timestamp_source = None
        add_error("timestamp", "REQUIRED_FIELD_MISSING", None,
                  "time_position与last_contact均为空，无法生成正常帧")

    # 呼号索引：可空；strip 后 1~8 个 ASCII
    callsign = get(1)
    if callsign is not None:
        callsign = callsign.strip()  # 去除首尾的空格
        if callsign == "":
            callsign = None
        elif not callsign.isascii() or len(callsign) > 8:
            add_error("callsign", "ENCODING_ERROR", callsign, "呼号必须为1~8个ASCII字符")
            callsign = None

    # 高度：优先 baro_altitude（索引7），回退 geo_altitude（索引13）
    baro_altitude = get(7)
    geo_altitude = get(13)
    if baro_altitude is not None:
        altitude: Any = baro_altitude
        alt_type: Any = "barometric"
    elif geo_altitude is not None:
        altitude = geo_altitude
        alt_type = "geometric"
    else:
        altitude = None
        alt_type = "unknown"

    # 可空数值字段（null 与真实 0 用 is None 区分）python读取null值直接转换为None
    lat = get(6)
    lon = get(5)
    speed = get(9)
    heading = get(10)
    vertical_rate = get(11)

    # 量程检查：越界字段置 None（视为无效），避免静默编码越界值
    def check_range(field_name: str, val: Any, lo: Any, hi: Any, desc: str) -> Any:
        if val is None:
            return None
        if (lo is not None and val < lo) \
                or (hi is not None and val > hi) \
                or (field_name == "heading" and val >= 360.0):
            add_error(field_name, "OUT_OF_RANGE", val, desc)
            return None
        return val

    lat = check_range("lat", lat, -90.0, 90.0, "纬度越界")
    lon = check_range("lon", lon, -180.0, 180.0, "经度越界")
    heading = check_range("heading", heading, 0.0, 360.0, "航向越界(需0<=heading<360)")
    speed = check_range("speed", speed, 0.0, None, "地速不能为负")
    vertical_rate = check_range("vertical_rate", vertical_rate, -327.68, 327.67, "垂直速度越界")

    return {
        "target_id": target_id,
        "callsign": callsign,
        "timestamp": timestamp,
        "timestamp_source": timestamp_source,
        "lat": lat,
        "lon": lon,
        "altitude": altitude,
        "alt_type": alt_type,
        "speed": speed,
        "heading": heading,
        "vertical_rate": vertical_rate,
        "on_ground": on_ground,
        "errors": errors,
    }

            

def calculate_checksum(data_without_checksum: bytes) -> int:
    """计算前39字节无符号字节值之和模65536。"""
    return sum(data_without_checksum[:39])%65536


def encode_position_message(record: dict[str, Any], message_seq: int) -> bytes:
    """按41字节TeachingLink格式封装一条位置状态消息。"""
    MAX_22 = 2 ** 22 - 1
    MAX_16 = 2 ** 16 - 1

    def q(y: float) -> int:
        return int(math.floor(y+0.5))

    def check_range(code: int, limit: int, field: str) -> None:
        if code < 0 or code > limit:
            raise ValueError(f"{field}编码越界：{code}")

    buf = bytearray(41)
    buf[0:2] = (0x4453).to_bytes(2,"big")
    buf[2] = 1
    buf[3] = 1
    buf[4:6] = (41).to_bytes(2,"big")
    buf[6:8] = (message_seq & 0xFFFF).to_bytes(2,"big")   #&0xffff的作用是只取16位，环形计数防止溢出
    buf[8:12] = int(record["timestamp"]).to_bytes(4,"big")
    buf[12:15] = int(record["target_id"],16).to_bytes(3,"big")  #int(num,16),num为16进制

    validity = 0
    status = 0

    """呼号"""
    callsign = record.get("callsign")
    if callsign is not None:
        raw = callsign.encode("ascii")
        buf[15:15 + len(raw)] = raw
        validity |= (1<<6)

    """纬度"""
    lat = record.get("lat")
    if lat is not None:
        code = q((lat + 90.0) / 180.0 * MAX_22)
        check_range(code,MAX_22,"lat")
        buf[23:26] = code.to_bytes(3,"big")
        validity |= (1<<0)

    """经度"""
    lon = record.get("lon")
    if lon is not None:
        code = q((lon + 180.0) / 360.0 * MAX_22)
        check_range(code,MAX_22,"lon")
        buf[26:29] = code.to_bytes(3,"big")
        validity |= (1<<1)

    """高度"""
    altitude = record.get("altitude")
    if altitude is not None:
        code = q(altitude + 1000.0)
        check_range(code,MAX_16,"altitude")
        buf[29:31] = code.to_bytes(2,"big")
        validity |= (1<<2)
        if record.get("alt_type") == "geometric":
            status |= (1<<1)

    """速度"""
    speed = record.get("speed")
    if speed is not None:
         code = q(speed / 0.1)
         check_range(code,MAX_16,"speed")
         buf[31:33] = code .to_bytes(2,"big")
         validity |= (1<<3)

    """航向"""
    heading = record.get("heading")
    if heading is not None:
        code = q(heading / 0.01)
        check_range(code,MAX_16,"heading")
        buf[33:35] = code.to_bytes(2,"big")
        validity |= (1<<4)

    """垂直速度"""
    vertical_rate = record.get("vertical_rate")
    if vertical_rate is not None:
        code = q((vertical_rate + 327.68) / 0.01)
        check_range(code,MAX_16,"vertical_rate")
        buf[35:37] = code.to_bytes(2,"big")
        validity |= (1<<5)
    if record.get("on_ground"):
        status |= (1<<0)
    if record.get("timestamp_source") == "last_contact_fallback":
        status |= (1<<2)

    buf[37] = status
    buf[38] = validity

    buf[39:41] = calculate_checksum(bytes(buf[0:39])).to_bytes(2,"big")

    return bytes(buf)



def decode_position_message(data: bytes) -> dict[str, Any]:
    """检查帧接收条件并恢复接收方结构化记录。"""
    MAX_22 = 2 ** 22 - 1

    # 结果字典：先给默认值，坏帧也能返回完整结构
    result: dict[str, Any] = {
        "target_id": None, "callsign": None, "timestamp": None,
        "time_source": None, "message_seq": None,
        "lat": None, "lon": None, "altitude": None, "alt_type": "unknown",
        "speed": None, "heading": None, "vertical_rate": None, "on_ground": False,
        "status_flags": None, "validity_flags": None,
        "latitude_code": None, "longitude_code": None,
        "altitude_code": None, "speed_code": None,
        "heading_code": None, "vertical_rate_code": None,
        "lat_valid": False, "lon_valid": False, "altitude_valid": False,
        "speed_valid": False, "heading_valid": False,
        "vertical_rate_valid": False, "callsign_valid": False,
        "checksum": None, "expected_checksum": None,
        "message_valid": False, "validation_errors": [],
    }
    errors: list[str] = []

    # 1. 长度与头部字段
    if len(data) != 41:
        result["validation_errors"] = ["LENGTH_ERROR"]
        return result
    magic = int.from_bytes(data[0:2], "big")
    msg_length = int.from_bytes(data[4:6], "big")
    if magic != 0x4453:
        errors.append("MAGIC_ERROR")
    if data[2] != 1:
        errors.append("VERSION_ERROR")
    if data[3] != 1:
        errors.append("MESSAGE_TYPE_ERROR")
    if msg_length != 41:
        errors.append("LENGTH_ERROR")

    # 2. 校验和：接收值 vs 重算值
    received_checksum = int.from_bytes(data[39:41], "big")
    expected_checksum = calculate_checksum(bytes(data[0:39]))
    result["checksum"] = received_checksum
    result["expected_checksum"] = expected_checksum
    if received_checksum != expected_checksum:
        errors.append("CHECKSUM_ERROR")

    # 3. 标志字节与协议整数
    status = data[37]
    validity = data[38]
    result["status_flags"] = status
    result["validity_flags"] = validity

    lat_code = int.from_bytes(data[23:26], "big")
    lon_code = int.from_bytes(data[26:29], "big")
    altitude_code = int.from_bytes(data[29:31], "big")
    speed_code = int.from_bytes(data[31:33], "big")
    heading_code = int.from_bytes(data[33:35], "big")
    vertical_rate_code = int.from_bytes(data[35:37], "big")
    callsign_bytes = data[15:23]
    result.update({
        "latitude_code": lat_code, "longitude_code": lon_code,
        "altitude_code": altitude_code, "speed_code": speed_code,
        "heading_code": heading_code, "vertical_rate_code": vertical_rate_code,
    })

    # 4. 保留位：经纬度容器最高2位、status bit3-7、validity bit7
    if (lat_code >> 22) != 0 or (lon_code >> 22) != 0 \
            or (status & 0b11111000) != 0 or (validity & 0x80) != 0:
        errors.append("RESERVED_BITS_ERROR")

    # 5. 标志/占位一致性：有效位0但占位非0
    for bit, code in [(1 << 0, lat_code), (1 << 1, lon_code),
                      (1 << 2, altitude_code), (1 << 3, speed_code),
                      (1 << 4, heading_code), (1 << 5, vertical_rate_code)]:
        if not (validity & bit) and code != 0:
            errors.append("FLAG_VALUE_INCONSISTENCY")
    if not (validity & (1 << 6)) and any(callsign_bytes):
        errors.append("FLAG_VALUE_INCONSISTENCY")

    # 6. 必需字段
    result["message_seq"] = int.from_bytes(data[6:8], "big")
    result["timestamp"] = int.from_bytes(data[8:12], "big")
    result["target_id"] = f"{int.from_bytes(data[12:15], 'big'):06x}"  # 保留前导0

    # 7. 状态与时间来源
    result["on_ground"] = bool(status & (1 << 0))
    result["time_source"] = "last_contact_fallback" if (status & (1 << 2)) else "position_time"

    # 8. 呼号：去尾部 \x00 补零后 ascii 解码
    callsign_valid = bool(validity & (1 << 6))
    result["callsign_valid"] = callsign_valid
    if callsign_valid:
        stripped = callsign_bytes.rstrip(b"\x00")
        try:
            result["callsign"] = stripped.decode("ascii")
        except UnicodeDecodeError:
            result["callsign"] = None
            errors.append("ENCODING_ERROR")

    # 9. 可空字段物理量恢复
    lat_valid = bool(validity & (1 << 0))
    lon_valid = bool(validity & (1 << 1))
    altitude_valid = bool(validity & (1 << 2))
    speed_valid = bool(validity & (1 << 3))
    heading_valid = bool(validity & (1 << 4))
    vertical_rate_valid = bool(validity & (1 << 5))
    result.update({
        "lat_valid": lat_valid, "lon_valid": lon_valid,
        "altitude_valid": altitude_valid, "speed_valid": speed_valid,
        "heading_valid": heading_valid, "vertical_rate_valid": vertical_rate_valid,
    })
    if lat_valid:
        result["lat"] = lat_code / MAX_22 * 180.0 - 90.0
    if lon_valid:
        result["lon"] = lon_code / MAX_22 * 360.0 - 180.0
    if altitude_valid:
        result["altitude"] = altitude_code - 1000.0
        result["alt_type"] = "geometric" if (status & (1 << 1)) else "barometric"
    if speed_valid:
        result["speed"] = speed_code * 0.1
    if heading_valid:
        result["heading"] = heading_code * 0.01
    if vertical_rate_valid:
        result["vertical_rate"] = vertical_rate_code * 0.01 - 327.68

    # 10. 校验枚举合法性并判定
    for err in errors:
        if err not in PROBLEM_TYPES:
            raise ValueError(f"非法problem_type：{err}")
    result["message_valid"] = (len(errors) == 0)
    result["validation_errors"] = errors
    return result

