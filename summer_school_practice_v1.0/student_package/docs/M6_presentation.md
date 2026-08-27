任务：把离线航空状态数据转换为发送方内部记录，封装成 41 字节二进制消息，模拟传输后在接收端解码、保存、形成航迹与当前态势，再完成语义映射与异常告警。
系统边界：TeachingLink 为学校自定义教学协议，不对应 ASTERIX/ADS-B/Link 16 或任何行业标准。
完整处理链：
OpenSky 离线数据 → 发送方解析与内部状态 → 教学消息封装 → 模拟传输
→ 接收方解封与校验 → CSV/SQLite(选做) → 航迹与当前态势
→ 语义映射与一致性检查 → 态势结果与告警







发送方解析：把 OpenSky 定长索引数组转为结构化记录，校验必需字段(target_id/timestamp/on_ground)，
处理可空字段、时间回退(time_position→last_contact)、高度回退(baro→geo)，量程越界置 None。
消息封装（41 字节，网络字节序大端）：
magic(0x4453) version type message_length message_seq timestamp target_id callsign
纬度/经度 22 位容器、高度 code=Q(alt+1000)、地速 code=Q(speed/0.1)、
航向 code=Q(heading/0.01)、垂直速度 code=Q((vr+327.68)/0.01)、
status_flags、validity_flags、checksum=前39字节之和 mod 65536
定点量化统一函数：Q(y) = floor(y + 0.5)，禁止用语言默认 round；编码前必须查量程。







接收判据（依次检查）：

1) 长度=41 且 message_length=41；2) magic/version/message_type 匹配；
2) checksum 一致；4) 经纬度容器最高2位与标志字节保留位为0；
3) 有效位与占位一致（有效位0但占位非0 → FLAG_VALUE_INCONSISTENCY）。
   可空字段按 validity_flags 逐位恢复：有效位1→按公式还原物理量，有效位0→None。
   真实零值(如 0.0)与缺失(None)通过有效位区分，不混淆。
   选做 SQLite：按 optional_db_schema.sql 建表，None 存为 NULL，写入后重读一致。







批量解码：按 41 字节切分（尾部残余字节记 LENGTH_ERROR 并忽略）。
航迹：仅可接受记录(message_valid=True 且 target_id、timestamp 可用)，
按 target_id 分组，组内按 timestamp 升序，track_sequence_no 从 1 连续编号。
当前态势：每个目标保留时间最新的可接受记录，track_length=该目标记录数；
可选字段缺失不丢记录。
示例：multitime 9 帧 → 3 目标航迹、3 目标当前态势。







语义映射：OpenSky/TeachingLink 两种来源映射到统一模型，source 标明来源。
TeachingLink 从协议码+标志位重推（比例因子/偏置/有效性）。
人工核验：候选映射仅作参考，纠正 5 处错误（经纬度互换、高度偏置 code-1000、
bit2 语义 time_source、呼号有效性位），补全缺失字段，每条映射含证据与 verified。
一致性检查：R1 位置缺失(HIGH)、R2 数据延迟、R3 重复、R4 航向越界(MEDIUM)；
按 HIGH>MEDIUM>NONE 合成 display_status(ERROR/WARNING/NORMAL)。
问题与改进：量化误差≤1量化单位；TeachingLink 非真实装备协议；
可从错误重传、多传感器融合、真实网络传输等方向扩展
