# M5 异常结果说明

- 批次时间：1710000120
- 四类必做规则是否均运行：是（R1 位置缺失、R2 数据延迟、R3 重复、R4 航向越界）
- 告警总数及按类型统计：共 4 条（POSITION_MISSING=1、DATA_DELAYED=1、DUPLICATE_RECORD=1、HEADING_OUT_OF_RANGE=1）
- HIGH/MEDIUM 数量：HIGH=1、MEDIUM=3
- 正常记录是否被误报：无（780abc 与 780aaa 首条均 NORMAL）
- heading=360 与 heading为空的处理：heading=360 按越界处理（MEDIUM）；heading 为空不触发该规则
- 字段缺失、帧验证失败、来源真实性三者的区别：
  - 字段缺失：有效位为0或值为空，属数据完整性范畴（对应 R1 位置缺失等）；
  - 帧验证失败：帧未通过长度/头字段/校验和/保留位/标志一致性等接收判据（选做 FRAME_VALIDATION_ERROR）；
  - 来源真实性：message_valid 只表示帧通过本规范格式与校验，不代表数据来源可信或安全完整性，二者不同。
