# M6综合运行说明

## 基本信息

- 姓名：谢吕遥
- 学号：10245101595
- GitHub用户名：fartoget-target
- Python版本：3.13.7
- 是否使用SQLite：是
- M4候选来源：学校预生成候选

## 安装与运行

先按课程包 `environment/README_environment.md` 建立独立 `.venv`。在课程包根目录清空 `student_package/output/` 后执行：

```powershell
.\.venv\Scripts\python.exe student_package\src_skeleton\run_all.py
```

M3.6 OpenSky 真实数据验证需单独运行：

```powershell
.\.venv\Scripts\python.exe student_package\src_skeleton\run_opensky_real.py
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

- 仓库链接：https://github.com/fartoget-target/data-link-10245101595-xielvyao.git
- 最终commit ID：18214984da9e86058ceb64e408567a775321b8ee
- 最后检查日期：2026.8.27
