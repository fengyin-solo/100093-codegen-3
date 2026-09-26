"""仪器设备业务规则：检定到期判定、检定记录校验与状态流转都收在这里。

检定口径约定：
- 仪器的有效检定日期以检定记录为准，同一仪器编号出现多次时取最近一次（检定日期最新、
  并列时登记 id 较大者）；没有检定记录才回落到仪器自身字段。
- 下次检定日距今天不足临期阈值的仪器自动标为「待检定」；阈值按保管人所在实验室区分，
  未配置的实验室按默认 30 天。
- 维修中、已停用的仪器不参与到期判定。
- 超过有效期仍处于使用状态（正常）的仪器必须拦下：强制转出正常使用并挂异常，
  在完成新的检定登记前不允许恢复「正常」。
"""
from __future__ import annotations

from datetime import date
from typing import Any

from app.store import store

MODULE = "instrument"
CALIBRATION_MODULE = "instrument_calibration"

REQUIRED_FIELDS = ["仪器编号", "仪器名称", "规格型号"]
CALIBRATION_REQUIRED_FIELDS = ["仪器编号", "检定日期", "下次检定日"]

STATUS_ORDER = ["正常", "待检定", "维修中", "已停用"]
EXEMPT_STATUSES = {"维修中", "已停用"}
ACTION_RULES = {"办理检定": "正常", "送修": "维修中", "停用仪器": "已停用"}
NEGATIVE_ACTIONS = ["停用仪器"]

# 临期阈值（天）按保管人所在实验室区分；未列出的实验室用默认 30 天
DEFAULT_DUE_THRESHOLD_DAYS = 30
LAB_DUE_THRESHOLD_DAYS = {
    "理化实验室": 30,
    "色谱实验室": 45,
    "微生物实验室": 15,
}

CONCLUSION_OK = "正常"
CONCLUSION_DUE = "临期待检"
CONCLUSION_OVERDUE = "已超期"
CONCLUSION_EXEMPT = "无需判定"


def _parse_date(value: Any) -> date | None:
    """把 YYYY-MM-DD 字符串解析成日期；空值或格式不对时返回 None。"""
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def threshold_for(lab: str | None) -> int:
    """保管人所在实验室的临期阈值；实验室未配置时回落到默认 30 天。"""
    return LAB_DUE_THRESHOLD_DAYS.get(str(lab or "").strip(), DEFAULT_DUE_THRESHOLD_DAYS)


class InstrumentService:
    def list_entries(
        self,
        *,
        keyword: str | None = None,
        status: str | None = None,
        page: int = 1,
        size: int = 20,
    ) -> tuple[list[dict[str, Any]], int]:
        today = date.today()
        self.refresh_due_status(today)
        rows = store.rows(MODULE)
        if keyword:
            rows = [row for row in rows if keyword in str(row.get("仪器编号", ""))]
        if status:
            rows = [row for row in rows if row.get("status") == status]
        total = len(rows)
        start = max(page - 1, 0) * size
        latest_map = self.latest_calibrations()
        return [self.decorate(row, today, latest_map) for row in rows[start:start + size]], total

    def get_entry(self, entry_id: int) -> dict[str, Any] | None:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None
        today = date.today()
        self.refresh_due_status(today)
        return self.decorate(entry, today, self.latest_calibrations())

    def create_entry(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        missing = [field for field in REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        date_error = self._check_date_pair(values.get("检定日期"), values.get("下次检定日"))
        if date_error:
            return None, date_error
        rows = store.rows(MODULE)
        entry = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        entry.update({field: values.get(field) for field in REQUIRED_FIELDS})
        for field in ("所属实验室", "检定日期", "下次检定日", "保管人"):
            entry[field] = values.get(field)
        entry["status"] = STATUS_ORDER[0]
        entry["pending"] = True
        entry["abnormal"] = False
        rows.append(entry)
        # 新登记的仪器同样按新口径标一遍，临期的一登记就是待检定
        self.refresh_due_status()
        return entry, "仪器已登记"

    def run_action(self, entry_id: int, action: str) -> tuple[dict[str, Any] | None, str]:
        entry = store.find(MODULE, entry_id)
        if entry is None:
            return None, f"仪器 {entry_id} 不存在或已归档"
        if action not in ACTION_RULES:
            return None, f"动作「{action}」不属于仪器设备可执行范围"
        target = ACTION_RULES[action]
        if target not in STATUS_ORDER:
            return None, f"目标状态「{target}」不在允许的状态序列里"
        if target == STATUS_ORDER[0]:
            conclusion = self.evaluate(entry)
            if conclusion["检定结论"] == CONCLUSION_OVERDUE:
                return None, (
                    f"仪器 {entry.get('仪器编号')} 已超过检定有效期"
                    f"（下次检定日 {conclusion['有效下次检定日']}），"
                    "不允许恢复使用，请先登记新的检定记录"
                )
        entry["status"] = target
        entry["pending"] = target != STATUS_ORDER[-1]
        entry["abnormal"] = action in NEGATIVE_ACTIONS
        entry["仪器状态"] = target
        return entry, f"仪器已{action}"

    def list_calibrations(self, code: str | None = None) -> list[dict[str, Any]]:
        """检定记录按仪器编号过滤，按检定日期倒序返回，最近一次排在最前。"""
        records = store.rows(CALIBRATION_MODULE)
        if code:
            records = [row for row in records if str(row.get("仪器编号", "")) == code]
        return sorted(
            records,
            key=lambda row: (_parse_date(row.get("检定日期")) or date.min, int(row.get("id", 0))),
            reverse=True,
        )

    def register_calibration(self, values: dict[str, Any]) -> tuple[dict[str, Any] | None, str]:
        """登记一条检定记录：检定日期晚于下次检定日的数据不允许保存。"""
        missing = [field for field in CALIBRATION_REQUIRED_FIELDS if not str(values.get(field) or "").strip()]
        if missing:
            return None, f"缺少必填字段：{'、'.join(missing)}"
        code = str(values.get("仪器编号") or "").strip()
        instrument = self._find_by_code(code)
        if instrument is None:
            return None, f"仪器编号 {code} 不存在，检定记录无法归档"
        date_error = self._check_date_pair(values.get("检定日期"), values.get("下次检定日"))
        if date_error:
            return None, date_error
        rows = store.rows(CALIBRATION_MODULE)
        record = {"id": max((int(row.get("id", 0)) for row in rows), default=0) + 1}
        record["检定编号"] = str(values.get("检定编号") or "").strip() or f"CAL-{record['id']:04d}"
        record.update({field: values.get(field) for field in CALIBRATION_REQUIRED_FIELDS})
        record["检定机构"] = values.get("检定机构")
        record["检定结果"] = values.get("检定结果") or "合格"
        record["记录人"] = values.get("记录人")
        rows.append(record)
        # 同一仪器编号以最近一次检定记录为准，同步仪器自身的日期字段
        latest = self.latest_calibrations().get(code)
        if latest is not None:
            instrument["检定日期"] = latest.get("检定日期")
            instrument["下次检定日"] = latest.get("下次检定日")
        # 新记录可能改变到期口径，既有仪器按新口径重标一遍
        summary = self.refresh_due_status()
        return record, (
            f"仪器 {code} 的检定记录已登记，"
            f"既有仪器已按新口径重标（待检定 {summary['待检定']} 台、超期拦截 {summary['已超期拦截']} 台）"
        )

    def refresh_due_status(self, today: date | None = None) -> dict[str, int]:
        """把既有仪器按新口径重新标一遍。

        临期自动转「待检定」；超过有效期还在使用状态的拦下——强制转出「正常」并挂异常；
        维修中、已停用不参与判定，保持原状态。
        """
        today = today or date.today()
        latest_map = self.latest_calibrations()
        summary = {"正常": 0, "待检定": 0, "已超期拦截": 0, "无需判定": 0}
        for entry in store.rows(MODULE):
            code = str(entry.get("仪器编号") or "").strip()
            latest = latest_map.get(code)
            if latest is not None:
                entry["检定日期"] = latest.get("检定日期")
                entry["下次检定日"] = latest.get("下次检定日")
            status = str(entry.get("status") or "")
            if status in EXEMPT_STATUSES:
                summary["无需判定"] += 1
                continue
            conclusion = self.evaluate(entry, today, latest_map)["检定结论"]
            if conclusion == CONCLUSION_OVERDUE:
                if status == STATUS_ORDER[0]:
                    summary["已超期拦截"] += 1
                entry["status"] = "待检定"
                entry["abnormal"] = True
            elif conclusion == CONCLUSION_DUE:
                entry["status"] = "待检定"
                entry["abnormal"] = False
                summary["待检定"] += 1
            else:
                entry["status"] = "正常"
                entry["abnormal"] = False
                summary["正常"] += 1
            entry["pending"] = entry["status"] != STATUS_ORDER[-1]
            entry["仪器状态"] = entry["status"]
        return summary

    def summary(self) -> dict[str, int]:
        """列表页统计卡片：各状态台数外加一个超期台数。"""
        today = date.today()
        self.refresh_due_status(today)
        latest_map = self.latest_calibrations()
        counts = {status: 0 for status in STATUS_ORDER}
        overdue = 0
        for entry in store.rows(MODULE):
            status = str(entry.get("status") or "")
            if status in counts:
                counts[status] += 1
            if self.evaluate(entry, today, latest_map)["检定结论"] == CONCLUSION_OVERDUE:
                overdue += 1
        counts["已超期"] = overdue
        return counts

    def latest_calibrations(self) -> dict[str, dict[str, Any]]:
        """按仪器编号取最近一次检定记录：检定日期最新者优先，并列时取登记 id 较大者。"""
        latest: dict[str, dict[str, Any]] = {}
        for record in store.rows(CALIBRATION_MODULE):
            code = str(record.get("仪器编号") or "").strip()
            if not code:
                continue
            key = (_parse_date(record.get("检定日期")) or date.min, int(record.get("id", 0)))
            current = latest.get(code)
            if current is None:
                latest[code] = record
                continue
            current_key = (_parse_date(current.get("检定日期")) or date.min, int(current.get("id", 0)))
            if key >= current_key:
                latest[code] = record
        return latest

    def evaluate(
        self,
        entry: dict[str, Any],
        today: date | None = None,
        latest_map: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """按新口径给单台仪器出检定结论，列表与详情都走这里保证一致。"""
        today = today or date.today()
        if latest_map is None:
            latest_map = self.latest_calibrations()
        code = str(entry.get("仪器编号") or "").strip()
        latest = latest_map.get(code)
        next_due_text = (latest or {}).get("下次检定日") or entry.get("下次检定日")
        next_due = _parse_date(next_due_text)
        threshold = threshold_for(str(entry.get("所属实验室") or ""))
        result: dict[str, Any] = {
            "检定结论": CONCLUSION_OK,
            "临期阈值": threshold,
            "距下次检定天数": None,
            "有效下次检定日": next_due.isoformat() if next_due else None,
        }
        if str(entry.get("status") or "") in EXEMPT_STATUSES:
            result["检定结论"] = CONCLUSION_EXEMPT
            return result
        if next_due is None:
            return result
        days = (next_due - today).days
        result["距下次检定天数"] = days
        if days < 0:
            result["检定结论"] = CONCLUSION_OVERDUE
        elif days < threshold:
            result["检定结论"] = CONCLUSION_DUE
        return result

    def decorate(
        self,
        entry: dict[str, Any],
        today: date | None = None,
        latest_map: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """输出前补上检定结论等计算字段；不改库里的原始行。"""
        row = dict(entry)
        conclusion = self.evaluate(entry, today, latest_map)
        row["检定结论"] = conclusion["检定结论"]
        row["临期阈值"] = conclusion["临期阈值"]
        row["距下次检定天数"] = conclusion["距下次检定天数"]
        if conclusion["有效下次检定日"]:
            row["下次检定日"] = conclusion["有效下次检定日"]
        return row

    def _find_by_code(self, code: str) -> dict[str, Any] | None:
        for row in store.rows(MODULE):
            if str(row.get("仪器编号", "")) == code:
                return row
        return None

    @staticmethod
    def _check_date_pair(calibrated_on: Any, next_due: Any) -> str | None:
        """检定日期晚于下次检定日的数据自相矛盾，不允许保存；两个日期齐全时才校验。"""
        start, end = _parse_date(calibrated_on), _parse_date(next_due)
        if start is not None and end is not None and start > end:
            return (
                f"检定日期 {start.isoformat()} 晚于下次检定日 {end.isoformat()}，"
                "数据自相矛盾，不允许保存"
            )
        return None
