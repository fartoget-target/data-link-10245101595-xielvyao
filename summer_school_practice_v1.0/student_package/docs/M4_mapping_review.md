# M4 AI辅助映射核验说明

## 候选来源
学校预生成候选：`reference/pre_generated_mapping_candidate.csv`（共 8 行，含故意错误，仅作参考）。

## 发现的字段、单位、层次、有效性或来源问题
1. 经纬度互换：候选将 `latitude_code+validity_flags.bit0` 映射到 `position.lon`、`longitude_code+validity_flags.bit1` 映射到 `position.lat`，实际应为纬度→`position.lat`、经度→`position.lon`。
2. 高度偏置错误：候选写"code乘1米"，实际应为 `code-1000`（1米分辨率、物理偏置1000米）。
3. 时间来源语义错误：候选将 `status_flags.bit2` 映射到 `quality.time_valid` 并"bit2=1设false"，实际 bit2 是 timestamp_fallback，应映射 `quality.time_source`（position_time/last_contact_fallback），时间回退不等于时间无效。
4. 呼号有效性位缺失：候选"去除补0后直接映射"，未按 `validity_flags.bit6` 判空。
5. 字段大量缺失：候选仅 8 行，缺 speed/heading/vertical_rate/on_ground/alt_type/position_valid/time_valid 及 OpenSky 的 message_valid 等，已按权威定义补全。

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
