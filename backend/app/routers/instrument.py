"""仪器设备接口：维护仪器与检定记录，覆盖办理检定、送修、停用仪器等动作。"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.instrument import InstrumentService

router = APIRouter(prefix="/api/instrument", tags=["仪器设备"])

service = InstrumentService()

LIST_FIELDS = ["仪器编号", "仪器名称", "规格型号", "所属实验室", "检定日期", "下次检定日", "保管人", "仪器状态", "检定结论"]
STATUSES = ["正常", "待检定", "维修中", "已停用"]


@router.get("/summary")
def summary() -> dict[str, int]:
    """列表页统计卡片：各状态台数与超期台数，口径与列表一致。"""
    return service.summary()


@router.get("/calibrations")
def list_calibrations(
    code: str | None = Query(default=None, description="按仪器编号过滤检定记录"),
) -> dict[str, Any]:
    """检定记录列表：同一仪器编号出现多次时最近一次排在最前。"""
    records = service.list_calibrations(code=code)
    return {"total": len(records), "items": records}


@router.post("/calibrations", response_model=ActionResult)
def register_calibration(payload: EntryPayload) -> ActionResult:
    """登记检定记录；检定日期晚于下次检定日的数据不允许保存并说明原因。"""
    record, message = service.register_calibration(payload.values)
    if record is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=record)


@router.post("/refresh", response_model=ActionResult)
def refresh_entries() -> ActionResult:
    """规则上线后的重标入口：把既有仪器按新口径重新标一遍。"""
    summary = service.refresh_due_status()
    message = (
        f"已按新口径重标：正常 {summary['正常']} 台、待检定 {summary['待检定']} 台、"
        f"超期拦截 {summary['已超期拦截']} 台、不参与判定 {summary['无需判定']} 台"
    )
    return ActionResult(ok=True, message=message, entry=summary)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出仪器设备清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "instrument", "total": total, "items": items}


@router.get("", response_model=PageResult[dict])
def list_entries(
    keyword: str | None = Query(default=None, description="按仪器编号检索"),
    status: str | None = Query(default=None, description="正常、待检定、维修中、已停用"),
    page: int = 1,
    size: int = 20,
) -> PageResult[dict]:
    """按仪器编号与状态过滤仪器设备列表；没有数据时返回空页，不报错。"""
    if size > 200:
        raise HTTPException(status_code=400, detail="每页最多 200 条，请缩小分页范围")
    items, total = service.list_entries(keyword=keyword, status=status, page=page, size=size)
    return PageResult(items=items, total=total, page=page, size=size)


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条仪器明细；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"仪器 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条仪器，缺字段或检定日期晚于下次检定日时说明原因而不是静默丢弃。"""
    entry, message = service.create_entry(payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条仪器执行办理检定、送修、停用仪器；超期仪器恢复使用会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
