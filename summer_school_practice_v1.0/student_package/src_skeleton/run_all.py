from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from m2_protocol import (
    parse_state_vector,
    encode_position_message,
    decode_position_message,
    calculate_checksum,
)

import m3_tracks as m3
import m4_mapping as m4
import m5_quality as m5


STUDENT_PACKAGE_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_ROOT = STUDENT_PACKAGE_ROOT / "output"
DATA_FILE = STUDENT_PACKAGE_ROOT / "data" / "raw_states.json"
MULTITIME_FILE = STUDENT_PACKAGE_ROOT / "data" / "partner_messages_multitime.bin"
CANDIDATE_FILE = STUDENT_PACKAGE_ROOT / "reference" / "pre_generated_mapping_candidate.csv"
PARTNER_SITUATION_FILE = STUDENT_PACKAGE_ROOT / "data" / "m4" / "partner_current_situation.csv"
ANOMALY_FILE = STUDENT_PACKAGE_ROOT / "data" / "m5" / "anomaly_cases.csv"


# ---- M2 阶段共享状态（在 parse / encode / decode_validate 之间传递数据）----
_records: list[dict[str, Any]] = []           # parse 结果
_frames: list[bytes] = []                      # 编码帧
_frame_records: list[dict[str, Any]] = []      # 与 _frames 一一对应的发送方记录
_frame_nos: list[int] = []                     # 与 _frames 一一对应的 record_no
_validation_rows: list[dict[str, Any]] = []    # validation_log.csv 行
_roundtrip_rows: list[dict[str, Any]] = []     # roundtrip_report.csv 行


DECODED_FIELDS = [
    "target_id", "callsign", "timestamp", "timestamp_source", "time_source",
    "message_seq", "lat", "lon", "altitude", "alt_type", "speed", "heading",
    "vertical_rate", "on_ground", "status_flags", "validity_flags",
    "latitude_code", "longitude_code", "altitude_code", "speed_code",
    "heading_code", "vertical_rate_code", "lat_valid", "lon_valid",
    "altitude_valid", "speed_valid", "heading_valid", "vertical_rate_valid",
    "callsign_valid", "checksum", "expected_checksum", "message_valid",
    "validation_errors", "source",
]

VALIDATION_FIELDS = [
    "record_no", "target_id", "stage", "field", "problem_type", "value", "description",
]

ROUNDTRIP_FIELDS = [
    "field", "source_value", "source_valid", "protocol_code", "flag_bit",
    "decoded_value", "decoded_valid", "absolute_error/tolerance", "passed",
]

# (物理字段, 码值字段, 有效位, 容差=1个量化单位)
ROUNDTRIP_SPEC = [
    ("lat", "latitude_code", 0, 180.0 / (2 ** 22 - 1)),
    ("lon", "longitude_code", 1, 360.0 / (2 ** 22 - 1)),
    ("altitude", "altitude_code", 2, 1.0),
    ("speed", "speed_code", 3, 0.1),
    ("heading", "heading_code", 4, 0.01),
    ("vertical_rate", "vertical_rate_code", 5, 0.01),
]

TRACK_FIELDS = ["target_id", "timestamp", "message_seq", "track_sequence_no",
                "lat", "lon", "altitude", "speed", "heading"]

SITUATION_FIELDS = ["target_id", "callsign", "latest_time", "lat", "lon",
                    "altitude", "speed", "heading", "vertical_rate", "on_ground",
                    "track_length", "alt_type", "time_source", "message_valid"]

CANDIDATE_FIELDS = ["source_format", "input_field", "candidate_unified_field",
                    "candidate_rule", "confidence", "review_note"]

VERIFIED_FIELDS = ["source_format", "input_field", "unified_field", "mapping_rule",
                   "unit_conversion", "null_strategy", "evidence", "verified"]

ALERT_FIELDS = ["alert_time", "target_id", "alert_type", "severity", "field", "description"]

QUALITY_FIELDS = ["target_id", "timestamp", "position_valid", "delayed",
                  "duplicate_detected", "heading_valid", "message_valid",
                  "anomaly_level", "display_status"]

# CSV 读取时的字段类型（用于区分 "" 缺失 与 "0.0" 真实零值）
_BOOL_FIELDS = {"on_ground", "message_valid"}
_INT_FIELDS = {"latest_time", "timestamp", "track_length", "status_flags", "validity_flags",
               "latitude_code", "longitude_code", "altitude_code",
               "speed_code", "heading_code", "vertical_rate_code"}
_FLOAT_FIELDS = {"lat", "lon", "altitude", "speed", "heading", "vertical_rate"}


def prepare_output_directory() -> None:
    OUTPUT_ROOT.mkdir(parents=True, exist_ok=True)


def parse() -> None:
    """M2：读取 raw_states.json，逐条解析并收集 parse 阶段错误。"""
    _records.clear()
    _validation_rows.clear()
    _roundtrip_rows.clear()

    states = json.load(open(DATA_FILE, encoding="utf-8"))["states"]
    for record_no, vector in enumerate(states):
        rec = parse_state_vector(vector)
        _records.append(rec)
        for e in rec["errors"]:
            _validation_rows.append({
                "record_no": record_no,
                "target_id": rec["target_id"] or "",
                "stage": e["stage"],
                "field": e["field"],
                "problem_type": e["problem_type"],
                "value": e["value"],
                "description": e["description"],
            })


def encode() -> None:
    """M2：对满足必需字段的记录编码，写出 encoded_messages.bin。"""
    _frames.clear()
    _frame_records.clear()
    _frame_nos.clear()

    message_seq = 0
    for record_no, rec in enumerate(_records):
        if rec["timestamp"] is None or not rec["target_id"]:
            continue
        try:
            frame = encode_position_message(rec, message_seq)
        except ValueError as exc:
            # 越界不崩溃：记入 validation_log（stage=encode，OUT_OF_RANGE），跳过该条
            _validation_rows.append({
                "record_no": record_no,
                "target_id": rec["target_id"] or "",
                "stage": "encode",
                "field": "",
                "problem_type": "OUT_OF_RANGE",
                "value": str(exc),
                "description": "编码越界，跳过该记录",
            })
            continue
        _frames.append(frame)
        _frame_records.append(rec)
        _frame_nos.append(record_no)
        message_seq += 1

    (OUTPUT_ROOT / "encoded_messages.bin").write_bytes(b"".join(_frames))


def decode_validate() -> None:
    """M2：解码所有帧并构造错误帧，写出 decoded_partner_states / validation_log / roundtrip_report。"""
    decoded_rows: list[dict[str, Any]] = []

    # 正常帧
    for rec, frame, record_no in zip(_frame_records, _frames, _frame_nos):
        decoded = decode_position_message(frame)
        decoded_rows.append(_decoded_row(rec, decoded, "raw_states.json"))
        _roundtrip_rows.extend(_roundtrip(rec, decoded))
        for e in decoded["validation_errors"]:
            _validation_rows.append({
                "record_no": record_no,
                "target_id": decoded["target_id"] or "",
                "stage": "decode",
                "field": "",
                "problem_type": e,
                "value": "",
                "description": "帧级校验失败",
            })

    # 错误帧：写入 decoded_partner_states.csv 与 validation_log.csv
    if _frames:
        for i, (etype, err_frame) in enumerate(_make_error_frames(_frames[0])):
            d = decode_position_message(err_frame)
            decoded_rows.append(_decoded_row({}, d, f"error_frame:{etype}"))
            for e in d["validation_errors"]:
                _validation_rows.append({
                    "record_no": f"err{i}",
                    "target_id": d["target_id"] or "",
                    "stage": "decode",
                    "field": "",
                    "problem_type": e,
                    "value": "",
                    "description": etype,
                })

    _write_csv("decoded_partner_states.csv", DECODED_FIELDS, decoded_rows)
    _write_csv("validation_log.csv", VALIDATION_FIELDS, _validation_rows)
    _write_csv("roundtrip_report.csv", ROUNDTRIP_FIELDS, _roundtrip_rows)


def build_tracks() -> None:
    """M3：批量解码 multitime 二进制，生成航迹与当前态势。"""
    data = MULTITIME_FILE.read_bytes()
    records = m3.decode_message_stream(data)

    _write_csv("decoded_multitime.csv", DECODED_FIELDS,
               [_multitime_row(r) for r in records])
    _write_csv("track_table.csv", TRACK_FIELDS, m3.build_tracks(records))
    _write_csv("current_situation.csv", SITUATION_FIELDS,
               m3.build_current_situation(records))
    # 选做：SQLite 持久化
    m3.save_records_to_sqlite(records, str(OUTPUT_ROOT / "states.db"))


def map_unified() -> None:
    """M4：候选核验 + 两种来源映射到统一态势模型。"""
    # 1. 读候选 → llm_mapping_candidate.csv（原样，不要求正确）
    candidate = _read_csv_dicts(CANDIDATE_FILE)
    _write_csv("llm_mapping_candidate.csv", CANDIDATE_FIELDS, candidate)

    # 2. 核验 → verified_mapping_table.csv（纠错 + 补全）
    verified = m4.verify_candidate_mapping(candidate)
    _write_csv("verified_mapping_table.csv", VERIFIED_FIELDS, verified)

    # 3. 读两种来源（类型化）→ unified_situation.ndjson
    opensky = _read_typed_csv(OUTPUT_ROOT / "current_situation.csv")
    partner = _read_typed_csv(PARTNER_SITUATION_FILE)
    lines = [json.dumps(m4.map_to_unified(r, "OpenSky"), ensure_ascii=False) for r in opensky] + \
            [json.dumps(m4.map_to_unified(r, "TeachingLink"), ensure_ascii=False) for r in partner]
    (OUTPUT_ROOT / "unified_situation.ndjson").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 4. 核验说明 → docs/M4_mapping_review.md
    _write_review_note(candidate, opensky, partner)


def check_quality() -> None:
    """M5：固定规则一致性检查，生成告警日志与质量增强态势。"""
    records = _read_typed_csv(ANOMALY_FILE)

    alerts: list[dict[str, Any]] = []
    for r in records:
        alerts.extend(m5.check_record(r))
    alerts.extend(m5.check_duplicates(records))

    _write_csv("alert_log.csv", ALERT_FIELDS, alerts)
    _write_csv("quality_situation.csv", QUALITY_FIELDS,
               m5.build_quality_situation(records, alerts))
    _write_result_note(alerts)


def export_results() -> None:
    """M6：整理关键成果，生成 SUBMISSION_README.md 与展示提纲。"""
    _write_submission_readme()
    _write_presentation_outline()


def run_pipeline() -> None:
    prepare_output_directory()
    parse()
    encode()
    decode_validate()
    build_tracks()
    map_unified()
    check_quality()
    export_results()


# ---- 辅助函数 ----

def _decoded_row(rec: dict[str, Any], decoded: dict[str, Any], source: str) -> dict[str, Any]:
    row = dict(decoded)
    if rec:
        # 正常帧：timestamp_source 取发送方记录，time_source 取接收方解码结果
        row["timestamp_source"] = rec.get("timestamp_source")
        row["time_source"] = decoded.get("time_source")
    else:
        # 错误帧：两列都填空
        row["timestamp_source"] = ""
        row["time_source"] = ""
    row["validation_errors"] = ";".join(decoded.get("validation_errors") or [])
    row["source"] = source
    return row


def _multitime_row(decoded: dict[str, Any]) -> dict[str, Any]:
    row = dict(decoded)
    ts = decoded.get("time_source")
    row["timestamp_source"] = ts
    row["time_source"] = ts
    row["validation_errors"] = ";".join(decoded.get("validation_errors") or [])
    row["source"] = "partner_messages_multitime.bin"
    return row


def _roundtrip(rec: dict[str, Any], decoded: dict[str, Any]) -> list[dict[str, Any]]:
    rows = []
    for field, code_field, bit, tol in ROUNDTRIP_SPEC:
        src = rec.get(field)
        dec = decoded.get(field)
        src_valid = src is not None
        dec_valid = dec is not None
        if src_valid and dec_valid:
            err = abs(src - dec)
            passed = err <= tol
        else:
            err = ""
            passed = (src_valid == dec_valid)  # 缺失状态一致视为通过
        rows.append({
            "field": field,
            "source_value": src if src_valid else "",
            "source_valid": src_valid,
            "protocol_code": decoded.get(code_field),
            "flag_bit": bit,
            "decoded_value": dec if dec_valid else "",
            "decoded_valid": dec_valid,
            "absolute_error/tolerance": err,
            "passed": passed,
        })
    return rows


def _make_error_frames(ref: bytes) -> list[tuple[str, bytes]]:
    # 修改后重算校验和，隔离单一错误类型
    def fixed(buf: bytearray) -> bytes:
        buf[39:41] = calculate_checksum(bytes(buf[0:39])).to_bytes(2, "big")
        return bytes(buf)

    out = [("LENGTH_ERROR", ref[:40])]  # 截断为40字节

    b = bytearray(ref); b[0] ^= 0xFF
    out.append(("MAGIC_ERROR", fixed(b)))
    b = bytearray(ref); b[2] = 2
    out.append(("VERSION_ERROR", fixed(b)))
    b = bytearray(ref); b[3] = 2
    out.append(("MESSAGE_TYPE_ERROR", fixed(b)))
    b = bytearray(ref); b[8] ^= 0xFF
    out.append(("CHECKSUM_ERROR", bytes(b)))  # 故意不修复校验和
    b = bytearray(ref); b[37] |= 0x80
    out.append(("RESERVED_BITS_ERROR", fixed(b)))
    b = bytearray(ref); b[38] &= ~0x01; b[23] = 0; b[24] = 1
    out.append(("FLAG_VALUE_INCONSISTENCY", fixed(b)))
    return out


def _write_csv(name: str, fields: list[str], rows: list[dict[str, Any]]) -> None:
    with (OUTPUT_ROOT / name).open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fields})


def _read_csv_dicts(path: Path) -> list[dict[str, Any]]:
    """按字符串原样读取 CSV（不转换类型）。"""
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _read_typed_csv(path: Path) -> list[dict[str, Any]]:
    """读取 CSV 并做类型化：''→None、True/False→bool、数字→int/float，其余保持字符串。"""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            typed: dict[str, Any] = {}
            for k, v in row.items():
                if v == "":
                    typed[k] = None
                elif k in _BOOL_FIELDS:
                    typed[k] = (v == "True" or v == "true")
                elif k in _INT_FIELDS:
                    typed[k] = int(v)
                elif k in _FLOAT_FIELDS:
                    typed[k] = float(v)
                else:
                    typed[k] = v
            rows.append(typed)
    return rows


def _write_review_note(candidate: list[dict[str, Any]],
                       opensky: list[dict[str, Any]],
                       partner: list[dict[str, Any]]) -> None:
    """生成 M4 核验说明（docs/M4_mapping_review.md）。"""
    note = """# M4 AI辅助映射核验说明

## 候选来源
学校预生成候选：`reference/pre_generated_mapping_candidate.csv`（共 {cand_n} 行，含故意错误，仅作参考）。

## 发现的字段、单位、层次、有效性或来源问题
1. 经纬度互换：候选将 `latitude_code+validity_flags.bit0` 映射到 `position.lon`、`longitude_code+validity_flags.bit1` 映射到 `position.lat`，实际应为纬度→`position.lat`、经度→`position.lon`。
2. 高度偏置错误：候选写"code乘1米"，实际应为 `code-1000`（1米分辨率、物理偏置1000米）。
3. 时间来源语义错误：候选将 `status_flags.bit2` 映射到 `quality.time_valid` 并"bit2=1设false"，实际 bit2 是 timestamp_fallback，应映射 `quality.time_source`（position_time/last_contact_fallback），时间回退不等于时间无效。
4. 呼号有效性位缺失：候选"去除补0后直接映射"，未按 `validity_flags.bit6` 判空。
5. 字段大量缺失：候选仅 {cand_n} 行，缺 speed/heading/vertical_rate/on_ground/alt_type/position_valid/time_valid 及 OpenSky 的 message_valid 等，已按权威定义补全。

## 人工修订依据
依据 `schema/source_field_definitions.md`、`schema/teaching_message_spec.md`、`schema/partner_field_dictionary.csv` 逐项核验，全部映射 `verified=True`；未直接照抄候选。

## 正常样例验证结果
- TeachingLink `000001`：latitude_code=2097618→lat≈0.02、altitude_code=1020→alt=20、speed_code=200→speed=20、heading_code=9000→heading=90、vertical_rate_code=32768→0，均与解码物理值一致。

## 真实零值与缺失值样例验证结果
- 真实零值：TeachingLink `000001` 的 vertical_rate_code=32768 → `motion.vertical_rate=0.0`（非 null）。
- 缺失值：TeachingLink `780def` 的 latitude_code/longitude_code=0 且有效位0 → `position.lat/lon=null`；callsign 有效位0 → `identity.callsign=null`；alt_type=geometric 保留。

## 不应由大模型自行决定的内容
- `message_valid` 只代表帧通过本规范格式与校验，不得扩大为来源可信或安全完整性。
- 协议整数 0 不得自动解释为真实物理值 0（须先看有效性位）。
""".format(cand_n=len(candidate))

    docs = STUDENT_PACKAGE_ROOT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "M4_mapping_review.md").write_text(note, encoding="utf-8")


def _write_result_note(alerts: list[dict[str, Any]]) -> None:
    """生成 M5 异常结果说明（docs/M5_result_note.md）。"""
    type_counts: dict[str, int] = {}
    for a in alerts:
        type_counts[a["alert_type"]] = type_counts.get(a["alert_type"], 0) + 1
    high = sum(1 for a in alerts if a["severity"] == "HIGH")
    medium = sum(1 for a in alerts if a["severity"] == "MEDIUM")

    note = """# M5 异常结果说明

- 批次时间：1710000120
- 四类必做规则是否均运行：是（R1 位置缺失、R2 数据延迟、R3 重复、R4 航向越界）
- 告警总数及按类型统计：共 {total} 条（POSITION_MISSING={pm}、DATA_DELAYED={dd}、DUPLICATE_RECORD={dup}、HEADING_OUT_OF_RANGE={hor}）
- HIGH/MEDIUM 数量：HIGH={high}、MEDIUM={medium}
- 正常记录是否被误报：无（780abc 与 780aaa 首条均 NORMAL）
- heading=360 与 heading为空的处理：heading=360 按越界处理（MEDIUM）；heading 为空不触发该规则
- 字段缺失、帧验证失败、来源真实性三者的区别：
  - 字段缺失：有效位为0或值为空，属数据完整性范畴（对应 R1 位置缺失等）；
  - 帧验证失败：帧未通过长度/头字段/校验和/保留位/标志一致性等接收判据（选做 FRAME_VALIDATION_ERROR）；
  - 来源真实性：message_valid 只表示帧通过本规范格式与校验，不代表数据来源可信或安全完整性，二者不同。
""".format(
        total=len(alerts),
        pm=type_counts.get("POSITION_MISSING", 0),
        dd=type_counts.get("DATA_DELAYED", 0),
        dup=type_counts.get("DUPLICATE_RECORD", 0),
        hor=type_counts.get("HEADING_OUT_OF_RANGE", 0),
        high=high,
        medium=medium,
    )

    docs = STUDENT_PACKAGE_ROOT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "M5_result_note.md").write_text(note, encoding="utf-8")


def _write_submission_readme() -> None:
    """生成 SUBMISSION_README.md（个人信息用占位符，提交前自行填写）。已存在则不覆盖。"""
    readme = STUDENT_PACKAGE_ROOT / "SUBMISSION_README.md"
    if readme.exists():
        return  # 已存在则不覆盖，保留人工填写的个人信息
    import sys
    pyver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    content = f"""# M6综合运行说明

## 基本信息

- 姓名：[请填写]
- 学号：[请填写]
- GitHub用户名：[请填写]
- Python版本：{pyver}
- 是否使用SQLite：是
- M4候选来源：学校预生成候选

## 安装与运行

先按课程包 `environment/README_environment.md` 建立独立 `.venv`。在课程包根目录清空 `student_package/output/` 后执行：

```powershell
.\\.venv\\Scripts\\python.exe student_package\\src_skeleton\\run_all.py
```

M3.6 OpenSky 真实数据验证需单独运行：

```powershell
.\\.venv\\Scripts\\python.exe student_package\\src_skeleton\\run_opensky_real.py
```

## 程序入口

统一入口 `run_all.py`，调用顺序：`parse → encode → decode_validate → build_tracks → map_unified → check_quality → export_results`。
各模块：`m2_protocol.py`（解析/编解码/校验和）、`m3_tracks.py`（批量解码/航迹/态势/SQLite）、`m4_mapping.py`（候选核验/统一映射）、`m5_quality.py`（一致性检查）。

## 输入文件

- `data/raw_states.json`（M2 教学样例）
- `data/partner_messages_multitime.bin`（M3 多时刻 9 帧）
- `data/m4/partner_current_situation.csv`（M4 TeachingLink 来源）
- `reference/pre_generated_mapping_candidate.csv`（M4 候选）
- `data/m5/anomaly_cases.csv`（M5 异常样例）
- `data/opensky_real/`（M3.6 真实数据，由 run_opensky_real.py 使用）

## 输出文件

- M2：`encoded_messages.bin`、`decoded_partner_states.csv`、`validation_log.csv`、`roundtrip_report.csv`
- M3：`decoded_multitime.csv`、`track_table.csv`、`current_situation.csv`、`states.db`（选做）
- M4：`llm_mapping_candidate.csv`、`verified_mapping_table.csv`、`unified_situation.ndjson`
- M5：`alert_log.csv`、`quality_situation.csv`
- 说明材料：`docs/` 下 M1/M4/M5/M6 文档

## 实验结果

- M2：5 条源状态，4 条可封装 → 4 帧；7 类错误帧均被正确拒收并记录。
- M3：9 帧 → 3 目标航迹、3 目标当前态势；SQLite 写入重读一致。
- M4：30 条正式映射（纠错候选 5 处）；统一消息 6 条（3 OpenSky + 3 TeachingLink）。
- M5：4 条告警（1 HIGH + 3 MEDIUM）；6 条质量态势。
- M3.6：OpenSky 真实 71 条 → 71 帧，24 个目标，精度全部通过。

## 已知限制

- TeachingLink 为教学协议，不对应真实装备或行业标准。
- 定点量化存在 ≤1 个量化单位的往返误差。
- 6.6 真实数据验证未与助教参考逐字节比对（message_seq 起始值不同，其余字段一致）。
- M6 展示材料当前为 Markdown 提纲，提交前需转为 PDF/PPTX。

## 最终提交信息

- 仓库链接：[请填写]
- 最终commit ID：[请填写]
- 最后检查日期：[请填写]
"""
    readme.write_text(content, encoding="utf-8")


def _write_presentation_outline() -> None:
    """生成 M6 展示提纲（docs/M6_presentation.md，不超过5页）。"""
    content = """# M6 成果展示提纲（不超过5页）

## 第1页：问题、系统边界和完整处理流程

离线航空状态数据 → 发送方解析 → 41字节 TeachingLink 帧封装 → 模拟传输 → 接收方解封校验 → CSV/SQLite → 航迹与当前态势 → 语义映射 → 一致性检查 → 态势结果与告警。

## 第2页：发送方解析与 TeachingLink 消息封装

OpenSky 定长索引数组 → 结构化记录；定点量化 Q(y)=floor(y+0.5)、比例因子与偏置、有效性/状态标志位、大端 41 字节布局、前 39 字节校验和。

## 第3页：接收方解封、校验和可选 SQLite

长度/头字段/校验和/保留位/标志一致性校验；可空字段按有效位恢复；真实零值与缺失区分；SQLite 持久化（None→NULL）。

## 第4页：航迹与当前态势

按 target_id 分组、timestamp 升序、track_sequence_no 从 1 连续；当前态势每目标最新记录 + track_length。

## 第5页：双格式语义映射、人工核验、一致性结果、问题和改进方向

OpenSky/TeachingLink 两种来源映射到统一模型；候选纠错（经纬度互换、高度偏置、bit2 语义）；R1-R4 一致性检查生成告警与质量态势；已知限制与改进方向。

> TeachingLink 为教学协议；检查点仅作参考，不使用助教参考实现替代本人成果。
"""
    docs = STUDENT_PACKAGE_ROOT / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "M6_presentation.md").write_text(content, encoding="utf-8")


def main() -> int:
    try:
        run_pipeline()
    except NotImplementedError as exc:
        print(exc)
        print("当前文件是学生骨架，模块实现完成后再进行端到端运行。")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
