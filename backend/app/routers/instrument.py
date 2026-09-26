"""仪器设备接口：维护仪器，覆盖办理检定、送修、停用仪器等动作。

检定判定口径都在 app.services.instrument 里：列表、详情、统计共用同一套结论，
保存与动作接口只做传参，不写业务判断。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, Query

from app.schemas import ActionResult, EntryPayload, PageResult
from app.services.instrument import InstrumentService

router = APIRouter(prefix="/api/instrument", tags=["仪器设备"])

service = InstrumentService()

LIST_FIELDS = ["仪器编号", "仪器名称", "规格型号", "所属实验室", "检定日期", "下次检定日", "保管人", "仪器状态"]
STATUSES = ["正常", "待检定", "维修中", "已停用"]


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


@router.get("/summary")
def summary() -> dict[str, Any]:
    """按检定结论统计仪器数量：临近到期、已超期的台数在这里一目了然。"""
    return service.summary()


@router.post("/refresh", response_model=ActionResult)
def refresh() -> ActionResult:
    """按新口径把既有仪器数据重新标一遍，返回重标统计。"""
    stats = service.refresh_statuses()
    message = (
        f"已按新口径重标：标为待检定 {stats['标为待检定']} 台、"
        f"恢复正常 {stats['恢复正常']} 台、不参与判定 {stats['不参与判定']} 台"
    )
    return ActionResult(ok=True, message=message, entry=stats)


@router.get("/export")
def export_entries() -> dict[str, Any]:
    """导出仪器设备清单：返回当前过滤条件下的全量数据。"""
    items, total = service.list_entries(page=1, size=10000)
    return {"module": "instrument", "total": total, "items": items}


@router.get("/{entry_id}", response_model=dict)
def get_entry(entry_id: int) -> dict:
    """读取单条仪器明细（含检定结论与检定记录）；不存在时给出可读的错误说明。"""
    entry = service.get_entry(entry_id)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"仪器 {entry_id} 不存在或已归档")
    return entry


@router.post("", response_model=ActionResult)
def create_entry(payload: EntryPayload) -> ActionResult:
    """登记一条仪器；缺字段或检定日期口径不符时不保存，并说明原因。"""
    entry, reasons = service.create_entry(payload.values)
    if reasons:
        return ActionResult(ok=False, message="；".join(reasons))
    return ActionResult(ok=True, message="仪器已登记", entry=entry)


@router.post("/{entry_id}/actions", response_model=ActionResult)
def run_action(entry_id: int, payload: EntryPayload) -> ActionResult:
    """对单条仪器执行办理检定、送修、停用仪器；超期或日期倒挂的会被拦下并说明原因。"""
    action = str(payload.values.get("action") or "").strip()
    entry, message = service.run_action(entry_id, action, payload.values)
    if entry is None:
        return ActionResult(ok=False, message=message)
    return ActionResult(ok=True, message=message, entry=entry)
