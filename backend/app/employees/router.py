from fastapi import APIRouter, Depends, HTTPException, status, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List
from pydantic import BaseModel
from app.database.database import get_db
from app.employees import service, schemas
from app.core.deps import get_current_user, require_permission
from app.auth.models import User

router = APIRouter(dependencies=[Depends(get_current_user)])


class AssignRolePayload(BaseModel):
    role_id: int


@router.get("/", response_model=List[schemas.EmployeeOut], dependencies=[Depends(require_permission("employee:view_all"))])
def read_employees(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return service.get_employees(db, skip=skip, limit=limit)

@router.post("/test-expiration-alerts", dependencies=[Depends(require_permission("employee:update"))])
async def trigger_expiration_alerts():
    """Manually trigger the nightly expiration alert job for testing."""
    from app.core.scheduler import check_expiring_designations
    await check_expiring_designations()
    return {"message": "Expiration checks triggered manually."}


@router.get("/panel-options", response_model=List[schemas.EmployeePanelOption])
def list_panel_options(db: Session = Depends(get_db)):
    """Return minimal active employee data for recruitment interview panel dropdowns."""
    employees = service.get_active_employees(db)
    return [schemas.EmployeePanelOption.from_employee(emp) for emp in employees]


@router.get("/{employee_id}/accrual-rules", dependencies=[Depends(require_permission("employee:view_all"))])
def get_accrual_rules(employee_id: int, db: Session = Depends(get_db)):
    """Return all monthly accrual rules for an employee."""
    from app.leave.accrual_models import EmployeeLeaveAccrualRule
    rules = db.query(EmployeeLeaveAccrualRule).filter(
        EmployeeLeaveAccrualRule.employee_id == employee_id
    ).all()
    return [
        {
            "leave_type_id": r.leave_type_id,
            "days_per_month": r.days_per_month,
            "period_start": str(r.period_start),
            "period_end": str(r.period_end) if r.period_end else None,
        }
        for r in rules
    ]


@router.put("/{employee_id}/role", dependencies=[Depends(require_permission("role:assign"))])
def assign_role_to_employee(employee_id: int, payload: AssignRolePayload, db: Session = Depends(get_db)):
    """Assign a role to an employee by updating their linked user account."""
    from app.roles.service import assign_roles_to_user
    from app.roles.schemas import AssignRoleRequest

    db_employee = service.get_employee_by_id(db, employee_id=employee_id)
    if db_employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    if not db_employee.user_id:
        raise HTTPException(status_code=400, detail="This employee has no linked user account.")

    return assign_roles_to_user(db, AssignRoleRequest(user_id=db_employee.user_id, role_ids=[payload.role_id]))


@router.get("/{employee_id}", response_model=schemas.EmployeeOut, dependencies=[Depends(require_permission("employee:view_all"))])
def read_employee(employee_id: int, db: Session = Depends(get_db)):
    db_employee = service.get_employee_by_id(db, employee_id=employee_id)
    if db_employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    return db_employee


@router.post("/", response_model=schemas.EmployeeOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_permission("employee:create"))])
def create_employee(
    employee: schemas.EmployeeCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    return service.create_employee(db, employee, background_tasks)


@router.put("/{employee_id}", response_model=schemas.EmployeeOut)
def update_employee(
    employee_id: int, 
    employee_update: schemas.EmployeeUpdate, 
    current_user: User = Depends(require_permission("employee:update")),
    db: Session = Depends(get_db)
):
    if current_user.employee and current_user.employee.id == employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot edit your own employee record. Another HR manager or admin must do this."
        )
    db_employee = service.update_employee(db=db, employee_id=employee_id, employee_update=employee_update)
    if db_employee is None:
        raise HTTPException(status_code=404, detail="Employee not found")
    return db_employee


@router.put("/{employee_id}/role", dependencies=[Depends(require_permission("role:assign"))])
def update_employee_role(
    employee_id: int, 
    payload: schemas.EmployeeRoleUpdate, 
    db: Session = Depends(get_db)
):
    success = service.update_employee_role(db, employee_id, payload.role_id)
    if not success:
        raise HTTPException(status_code=404, detail="Employee or User not found")
    return {"success": True, "message": "Role assigned successfully"}


@router.delete("/{employee_id}", dependencies=[Depends(require_permission("employee:delete"))])
def delete_employee(employee_id: int, db: Session = Depends(get_db)):
    success = service.delete_employee(db=db, employee_id=employee_id)
    if not success:
        raise HTTPException(status_code=404, detail="Employee not found")
    return {"success": True, "message": "Employee deleted successfully"}


@router.post("/{employee_id}/resend-login-details")
def resend_login_details(
    employee_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(require_permission("employee:create")),
):
    """Email the employee a new temporary password (forced change on next login)."""
    return service.resend_login_details(db, employee_id, current_user, background_tasks)


@router.post("/test-email", dependencies=[Depends(require_permission("employee:create"))])
def test_email(email: str):
    """Trigger a test welcome email to a specific address."""
    from app.employees.email import send_welcome_email
    send_welcome_email(email, "Test Admin", "test-password-123")
    return {"message": f"Test email triggered for {email}. Check backend logs for results."}


@router.get("/{employee_id}/designation-history", 
            response_model=List[schemas.DesignationHistoryEntry],
            dependencies=[Depends(require_permission("employee:view_all"))])
def get_designation_history(employee_id: int, db: Session = Depends(get_db)):
    return service.get_designation_history(db, employee_id)
