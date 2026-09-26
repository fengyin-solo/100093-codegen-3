"""仪器设备业务规则：检定到期判定、状态流转、字段校验与筛选口径都收在这里。

检定判定口径（列表与详情共用同一个 evaluate，结论必然一致）：
- 下次检定日距今天不足临期阈值的仪器，自动标为「待检定」；
- 临期阈值按保管人所在实验室（所属实验室）区分，未配置的实验室用默认 30 天；
- 检定日期晚于下次检定日的数据不允许保存，保存时说明原因；
- 超过检定有效期仍要保持「正常」（使用状态）的仪器一律拦下；
- 「维修中」「已停用」的仪器不参与到期判定；
- 同一仪器编号在检定记录里出现多次时，以检定日期最近的一条为准。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "instrument"
CALIBRATION_MODULE = "instrument_calibration"
REQUIRED_FIELDS = ["仪器编号", "仪器名称", "规格型号"]
EDITABLE_FIELDS = ["仪器编号", "仪器名称", "规格型号", "所属实验室", "检定日期", "下次检定日", "保管人"]
STATUS_ORDER = ["正常", "待检定", "维修中", "已停用"]
EXEMPT_STATUSES = {"维修中", "已停用"}
ACTION_RULES = {"办理检定": "正常", "送修": "维修中", "停用仪器": "已停用"}
NEGATIVE_ACTIONS = ["停用仪器"]

DEFAULT_DUE_THRESHOLD_DAYS = 30
# 临期阈值按保管人所在实验室区分；不在表里的实验室走默认 30 天
LAB_DUE_THRESHOLD_DAYS = {
    "理化实验室": 30,
    "色谱实验室": 45,
    "微生物实验室": 15,
}

CONCLUSION_OK = "在检定期内"
CONCLUSION_DUE_SOON = "临近到期"
CONCLUSION_OVERDUE = "已超期"
CONCLUSION_EXEMPT = "不参与判定"
CONCLUSION_NO_DATE = "待完善日期"
CONCLUSIONS = [CONCLUSION_OK, CONCLUSION_DUE_SOON, CONCLUSION_OVERDUE, CONCLUSION_EXEMPT, CONCLUSION_NO_DATE]


def parse_day(value: Any) -> date | None:
    """把 YYYY-MM-DD 字符串解析成日期；空值或格式不对时返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def lab_threshold_days(lab: Any) -> int:
    """保管人所在实验室的临期阈值；未配置的实验室用默认 30 天。"""
    return LAB_DUE_THRESHOLD_DAYS.get(str(lab or "").strip(), DEFAULT_DUE_THRESHOLD_DAYS)


class InstrumentService:
    def __init__(self) -> None:
        # 规则上线后，先把既有仪器数据按新口径重标一遍
        self.refresh_statuses()

    # ---------- 检定记录 ----------
    def latest_calibration(self, instrument_code: str) -> dict[str, Any] | None:
        """同一仪器编号出现多条检定记录时，以检定日期最近的一条为准。"""
        records = [
            row for row in store.rows(CALIBRATION_MODULE)
            if str(row.get("仪器编号") or "") == instrument_code
        ]
        if not records:
            return None
        return max(
            records,
            key=lambda row: (parse_day(row.get("检定日期")) or date.min, int(row.get("id", 0))),
        )

    def calibration_records(self, instrument_code: str) -> list[dict[str, Any]]:
        """某台仪器的全部检定记录，最近的排在前面。"""
        records = [
            row for row in store.rows(CALIBRATION_MODULE)
            if str(row.get("仪器编号") or "") == instrument_code
        ]
        return sorted(
            records,
            key=lambda row: (parse_day(row.get("检定日期")) or date.min, int(row.get("id", 0))),
            reverse=True,
        )

    def effective_dates(self, entry: dict[str, Any]) -> tuple[date | None, date | None, str]:
        """检定日期的取值口径：有检定记录以最近一次记录为准，否则用仪器台账上的字段。"""
        record = self.latest_calibration(str(entry.get("仪器编号") or ""))
        if record is not None:
            return parse_day(record.get("检定日期")), parse_day(record.get("下次检定日")), "检定记录"
        return parse_day(entry.get("检定日期")), parse_day(entry.get("下次检定日")), "仪器台账"

    # ---------- 到期判定 ----------
    def evaluate(self, entry: dict[str, Any], *, today: date | None = None) -> dict[str, Any]:
        """单台仪器的检定结论：结论、距到期天数、适用阈值与原因说明。"""
        today = today or date.today()
        status = str(entry.get("status") or "")
        threshold = lab_threshold_days(entry.get("所属实验室"))
        if status in EXEMPT_STATUSES:
            return {
                "检定结论": CONCLUSION_EXEMPT,
                "距到期天数": None,
                "适用阈值": threshold,
                "结论原因": f"{status}的仪器不参与到期判定",
            }
        _, next_day, source = self.effective_dates(entry)
        if next_day is None:
            return {
                "检定结论": CONCLUSION_NO_DATE,
                "距到期天数": None,
                "适用阈值": threshold,
                "结论原因": "缺少有效的下次检定日，无法判定",
            }
        remaining = (next_day - today).days
        if remaining < 0:
            conclusion = CONCLUSION_OVERDUE
            reason = f"下次检定日 {next_day.isoformat()} 已过，超过有效期 {-remaining} 天"
        elif remaining < threshold:
            conclusion = CONCLUSION_DUE_SOON
            reason = f"距下次检定日 {next_day.isoformat()} 还有 {remaining} 天，不足 {threshold} 天阈值"
        else:
            conclusion = CONCLUSION_OK
            reason = f"距下次检定日 {next_day.isoformat()} 还有 {remaining} 天"
        return {
            "检定结论": conclusion,
            "距到期天数": remaining,
            "适用阈值": threshold,
            "结论原因": reason,
            "日期来源": source,
        }

    def refresh_statuses(self, *, today: date | None = None) -> dict[str, int]:
        """按新口径把既有仪器重标一遍：临近到期或已超期的标为待检定，
        回到检定期内的恢复为正常；维修中、已停用不参与判定，保持原状态。"""
        today = today or date.today()
        stats = {"标为待检定": 0, "恢复正常": 0, "不参与判定": 0}
        for entry in store.rows(MODULE):
            if str(entry.get("status") or "") in EXEMPT_STATUSES:
                stats["不参与判定"] += 1
                continue
            conclusion = self.evaluate(entry, today=today)["检定结论"]
            if conclusion in (CONCLUSION_DUE_SOON, CONCLUSION_OVERDUE):
                if entry.get("status") != "待检定":
                    stats["标为待检定"] += 1
                entry["status"] = "待检定"
            elif conclusion == CONCLUSION_OK and entry.get("status") == "待检定":
                entry["status"] = "正常"
                stats["恢复正常"] += 1
        return stats

    # ---------- 查询 ----------
    def _with_conclusion(self, entry: dict[str, Any], *, today: date) -> dict[str, Any]:
        row = dict(entry)
        row["仪器状态"] = entry.get("status")
        row.update(self.evaluate(entry, today=today))
        return row

    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        today = date.today()
        # 每次读取前按当天口径重标，保证列表与详情看到的结论一致
        self.refresh_statuses(today=today)
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("仪器编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        return [self._with_conclusion(row, today=today) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        today = date.today()
        self.refresh_statuses(today=today)
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        row = self._with_conclusion(entry, today=today)
        row["检定记录"] = self.calibration_records(str(entry.get("仪器编号") or ""))
        return row

    def summary(self) -> dict[str, Any]:
        """按检定结论统计仪器数量，给前端做临期与超期提示。"""
        today = date.today()
        self.refresh_statuses(today=today)
        counts = {conclusion: 0 for conclusion in CONCLUSIONS}
        for entry in store.rows(MODULE):
            counts[self.evaluate(entry, today=today)["检定结论"]] += 1
        return {
            "结论统计": counts,
            "默认阈值": DEFAULT_DUE_THRESHOLD_DAYS,
            "实验室阈值": dict(LAB_DUE_THRESHOLD_DAYS),
        }

    # ---------- 保存口径 ----------
    def _validate_date_pair(self, cal_text: str, next_text: str, *, today: date) -> str | None:
        """保存口径：日期必须合法、检定日期不得晚于下次检定日、
        超过有效期的仪器不能保持使用状态。通过时返回 None，否则返回原因。"""
        cal_day = parse_day(cal_text)
        next_day = parse_day(next_text)
        if cal_day is None or next_day is None:
            return "检定日期与下次检定日需按 YYYY-MM-DD 填写"
        if cal_day > next_day:
            return f"检定日期 {cal_day.isoformat()} 晚于下次检定日 {next_day.isoformat()}，数据不允许保存"
        if next_day < today:
            return f"下次检定日 {next_day.isoformat()} 已超过有效期，仪器不能保持使用状态，请先办理检定"
        return None

    def _append_calibration(
        self,
        entry: dict[str, Any],
        cal_text: str,
        next_text: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        """把一次检定写进检定记录台账，同一仪器编号以最近一次为准。"""
        rows = store.rows(CALIBRATION_MODULE)
        record = {
            "id": max((int(row.get("id", 0)) for row in rows), default=0) + 1,
            "记录编号": f"CAL-{max((int(row.get('id', 0)) for row in rows), default=0) + 1:04d}",
            "仪器编号": entry.get("仪器编号"),
            "检定日期": cal_text,
            "下次检定日": next_text,
            "检定机构": str(values.get("检定机构") or "").strip() or "待补充",
            "检定人": str(values.get("检定人") or "").strip() or str(entry.get("保管人") or ""),
        }
        rows.append(record)
        return record

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
        today = date.today()
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, [f"缺少必填字段：{'、'.join(missing)}"]
        code = str(values.get("仪器编号") or "").strip()
        if any(str(row.get("仪器编号") or "") == code for row in store.rows(MODULE)):
            return None, [f"仪器编号 {code} 已存在，检定记录按仪器编号归集，不能重复登记"]
        cal_text = str(values.get("检定日期") or "").strip()
        next_text = str(values.get("下次检定日") or "").strip()
        if cal_text or next_text:
            reason = self._validate_date_pair(cal_text, next_text, today=today)
            if reason:
                return None, [reason]
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in EDITABLE_FIELDS})
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        if cal_text and next_text:
            self._append_calibration(entry, cal_text, next_text, values)
        self.refresh_statuses(today=today)
        return self._with_conclusion(entry, today=today), []

    def run_action(
        self,
        entry_id: int,
        action: str,
        values: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any] | None, str]:
        today = date.today()
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"仪器 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于仪器设备可执行范围"
        values = values or {}
        if action == "办理检定":
            cal_text = str(values.get("检定日期") or "").strip()
            next_text = str(values.get("下次检定日") or "").strip()
            if not cal_text or not next_text:
                return None, "办理检定需同时填写检定日期与下次检定日"
            reason = self._validate_date_pair(cal_text, next_text, today=today)
            if reason:
                return None, reason
            self._append_calibration(entry, cal_text, next_text, values)
            entry["检定日期"] = cal_text
            entry["下次检定日"] = next_text
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        self.refresh_statuses(today=today)
        row = self._with_conclusion(entry, today=today)
        if action == "办理检定" and entry.get("status") == "待检定":
            reason = row["结论原因"]
            return row, f"仪器已办理检定，但{reason}，状态仍为待检定"
        return row, f"仪器已{action}"
