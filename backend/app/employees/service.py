from sqlalchemy.orm import Session
from app.employees.models import Employee
from app.employees.schemas import EmployeeCreate, EmployeeUpdate

import secrets
import string
import logging
from fastapi import HTTPException, status, BackgroundTasks
from app.auth.models import User
from app.roles.models import Role
from app.core.security import hash_password
from app.employees import email as _email_module

logger = logging.getLogger(__name__)


def _issue_temporary_password(user: User) -> str:
    """
    Give `user` a fresh emailed-style temporary password and return it.

    The account is forced through the first-login change (must_change_password),
    the password expires after TEMP_PASSWORD_EXPIRE_DAYS, and every existing
    session is revoked (refresh_token cleared).
    """
    from datetime import datetime, timedelta
    from app.core.config import TEMP_PASSWORD_EXPIRE_DAYS

    temp_password = "".join(secrets.choice(string.ascii_letters + string.digits) for _ in range(12))
    user.password_hash = hash_password(temp_password)
    user.must_change_password = True
    user.temp_password_expires_at = datetime.utcnow() + timedelta(days=TEMP_PASSWORD_EXPIRE_DAYS)
    user.refresh_token = None
    return temp_password


def get_employees(db: Session, skip: int = 0, limit: int = 100):
    from sqlalchemy.orm import joinedload
    return db.query(Employee).options(
        joinedload(Employee.department_rel),
        joinedload(Employee.user).joinedload(User.roles)
    ).filter(
        (Employee.is_deleted == False) | (Employee.is_deleted == None)
    ).offset(skip).limit(limit).all()


def get_employee_by_id(db: Session, employee_id: int):
    from sqlalchemy.orm import joinedload
    return db.query(Employee).options(
        joinedload(Employee.department_rel),
        joinedload(Employee.user).joinedload(User.roles),
        joinedload(Employee.designation_history)
    ).filter(
        Employee.id == employee_id,
        (Employee.is_deleted == False) | (Employee.is_deleted == None)
    ).first()


def get_all_employees(db: Session):
    """Return all non-deleted employees ordered by name. Used by recruitment panel dropdowns."""
    from sqlalchemy.orm import joinedload
    return db.query(Employee).options(
        joinedload(Employee.department_rel),
        joinedload(Employee.user).joinedload(User.roles)
    ).filter(
        (Employee.is_deleted == False) | (Employee.is_deleted == None)
    ).order_by(Employee.last_name, Employee.first_name).all()


def get_active_employees(db: Session):
    """Return only active employees. Used by recruitment interview panel dropdowns."""
    from sqlalchemy.orm import joinedload
    from app.leave.models import EmployeeLeaveEntitlement
    from app.leave.models import EmployeeLeaveEntitlement
    from app.leave.models import EmployeeLeaveAccrualRule
    
    flat_ids = {r[0] for r in db.query(EmployeeLeaveEntitlement.employee_id).distinct().all()}
    accrual_ids = {r[0] for r in db.query(EmployeeLeaveAccrualRule.employee_id).distinct().all()}
    overridden_ids = flat_ids.union(accrual_ids)
    
    employees = db.query(Employee).options(
        joinedload(Employee.user).joinedload(User.roles),
        joinedload(Employee.department_rel),
    ).filter(
        Employee.status == "active",
        (Employee.is_deleted == False) | (Employee.is_deleted == None)
    ).order_by(Employee.last_name, Employee.first_name).all()
    
    for emp in employees:
        emp.has_leave_override = emp.id in overridden_ids
        
    return employees


def create_employee(db: Session, employee: EmployeeCreate, background_tasks: BackgroundTasks):
    """
    Unified creation flow:
    1. Create User account with random password
    2. Create Employee record linked to User
    3. Assign initial Role to User
    4. Send welcome email after commit (via BackgroundTasks)
    """
    # Validate any pre-assigned leave entitlements up front so a bad value fails
    # cleanly (400) instead of a rolled-back 500 on an FK/constraint violation,
    # and so negative days can never be stored (mirrors set_employee_leave_entitlements).
    if employee.designation_leave_overrides:
        from app.leave.models import LeaveType as _LeaveType
        _seen_types: set[int] = set()
        for ent in employee.designation_leave_overrides:
            if ent.days is None or ent.days < 0 or ent.days > 365:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Pre-assigned leave days must be between 0 and 365.",
                )
            if ent.leave_type_id in _seen_types:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="The same leave type was pre-assigned more than once.",
                )
            _seen_types.add(ent.leave_type_id)
            if not db.query(_LeaveType).filter(_LeaveType.id == ent.leave_type_id).first():
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Unknown leave type in pre-assigned entitlements (id {ent.leave_type_id}).",
                )

    try:
        # A soft-deleted user/employee may still hold this email or employee_id.
        # That is fine: uniqueness is enforced by PARTIAL unique indexes scoped to
        # live rows (WHERE is_deleted = false), so a new active record can reuse the
        # identifiers of a soft-deleted one. If an *active* row already holds them,
        # the insert raises IntegrityError, mapped to a friendly 400 below.
        db_user = User(
            username=employee.email,
            email=employee.email,
            is_active=True,
            first_name=employee.first_name,
            last_name=employee.last_name,
            employee_id=employee.employee_id,
            phone_number=employee.phone,
            address=employee.address,
            date_of_birth=str(employee.date_of_birth) if employee.date_of_birth else None,
            emergency_contact_number=employee.emergency_contact_phone,
            position=employee.designation
        )
        # The temporary password travels by email, so it must be replaced on
        # first login before the account can be used (core/deps.py).
        temp_password = _issue_temporary_password(db_user)
        db.add(db_user)
        db.flush()

        employee_data = employee.model_dump(exclude={"role_id", "designation_id", "designation_start_date", "designation_end_date", "designation_leave_overrides", "designation_accrual_rules"})
        db_employee = Employee(**employee_data, user_id=db_user.id)
        db.add(db_employee)
        db.flush()

        # --- Designation history ---
        if employee.designation_id or employee.designation:
            from app.designations.models import Designation as _Designation
            from app.employees.models import EmployeeDesignationHistory
            from datetime import date as _date

            desig_name = employee.designation or ""
            if employee.designation_id:
                d = db.query(_Designation).filter(_Designation.id == employee.designation_id).first()
                if d:
                    desig_name = d.name
                    db_employee.designation = desig_name      # sync string field
                    db_employee.designation_id = employee.designation_id

            hist = EmployeeDesignationHistory(
                employee_id=db_employee.id,
                designation_id=employee.designation_id,
                designation_name=desig_name,
                start_date=employee.designation_start_date or employee.joined_date or _date.today(),
                end_date=employee.designation_end_date,
                leave_overrides=[e.model_dump() for e in employee.designation_leave_overrides] 
                                 if employee.designation_leave_overrides else None,
            )
            db.add(hist)
            db.flush()

        # If leave overrides were provided at creation time, write them to EmployeeLeaveEntitlement
        # so the leave module immediately sees the custom allocation (not just in history JSON).
        # Skip leave types that are configured as monthly accrual — they are handled separately.
        _accrual_type_ids: set[int] = {
            r.leave_type_id for r in (employee.designation_accrual_rules or [])
        }
        if employee.designation_leave_overrides:
            from app.leave.models import EmployeeLeaveEntitlement as _ELE, LeaveType as _LeaveType2
            for override in employee.designation_leave_overrides:
                if override.leave_type_id in _accrual_type_ids:
                    continue  # accrual mode takes precedence for this type
                lt = db.query(_LeaveType2).filter(_LeaveType2.id == override.leave_type_id).first()
                if not lt:
                    continue
                row = db.query(_ELE).filter(
                    _ELE.employee_id == db_employee.id,
                    _ELE.leave_type_id == override.leave_type_id,
                ).first()
                if row:
                    row.days = override.days
                else:
                    db.add(_ELE(
                        employee_id=db_employee.id,
                        leave_type_id=override.leave_type_id,
                        days=override.days,
                    ))

        # Persist monthly accrual rules (the new optional feature).
        if employee.designation_accrual_rules:
            from app.leave.accrual_models import EmployeeLeaveAccrualRule as _ELAR
            from app.leave.models import LeaveType as _LeaveType3
            from datetime import date as _date
            _accrual_start = employee.designation_start_date or employee.joined_date or _date.today()
            for rule in employee.designation_accrual_rules:
                if not db.query(_LeaveType3).filter(_LeaveType3.id == rule.leave_type_id).first():
                    continue
                existing_rule = db.query(_ELAR).filter(
                    _ELAR.employee_id == db_employee.id,
                    _ELAR.leave_type_id == rule.leave_type_id,
                ).first()
                if existing_rule:
                    existing_rule.days_per_month = rule.days_per_month
                    existing_rule.period_start = _accrual_start
                    existing_rule.period_end = employee.designation_end_date
                    existing_rule.max_carry_forward = None
                    existing_rule.total_leaves_cap = rule.total_leaves_cap
                    existing_rule.carry_forward_allowed = rule.carry_forward_allowed
                else:
                    db.add(_ELAR(
                        employee_id=db_employee.id,
                        leave_type_id=rule.leave_type_id,
                        days_per_month=rule.days_per_month,
                        period_start=_accrual_start,
                        period_end=employee.designation_end_date,
                        max_carry_forward=None,
                        total_leaves_cap=rule.total_leaves_cap,
                        carry_forward_allowed=rule.carry_forward_allowed,
                    ))

        # Eager-load permissions so the relationship is fully populated after commit
        from sqlalchemy.orm import joinedload as _jl
        role = db.query(Role).options(_jl(Role.permissions)).filter(Role.id == employee.role_id).first()
        if not role:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Role ID {employee.role_id} not found"
            )

        db_user.roles = [role]
        db_user.role_id = role.id

        from app.departments.models import Department
        dept = db.query(Department).filter(Department.id == employee.department_id).first()
        if dept:
            db_user.department = dept.name



        db.commit()
        db.refresh(db_employee)

        # ── Notify the new employee ──────────────────────────────────────
        try:
            from app.notifications.service import notify_user
            notify_user(
                db, db_user.id,
                f"Welcome to the team, {db_employee.first_name}!",
                category="system", type="success", link="/dashboard",
                entity_type="employee", entity_id=str(db_employee.id),
            )
            db.commit()
        except Exception as e:
            logger.error(f"Notification failed for new employee: {e}")

        full_name = f"{db_employee.first_name} {db_employee.last_name}"
        from app.core.config import TEMP_PASSWORD_EXPIRE_DAYS
        background_tasks.add_task(
            _email_module.send_welcome_email, db_employee.email, full_name, temp_password,
            expires_days=TEMP_PASSWORD_EXPIRE_DAYS,
        )

        return db_employee

    except Exception as e:
        db.rollback()
        logger.error(f"Failed to create employee/user: {str(e)}")

        error_msg = str(e).lower()
        # Map the partial-unique-index violation on a LIVE row to a clean 400.
        # The whole create runs in one transaction and was rolled back above, so
        # no half-created User/Employee is left behind (REQ-EMP-08).
        if "email_active" in error_msg or "ix_users_email" in error_msg or ("unique constraint" in error_msg and "email" in error_msg):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This email is already used.")
        if "username_active" in error_msg or "ix_users_username" in error_msg or ("unique constraint" in error_msg and "username" in error_msg):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This username is already used.")
        if "employee_id_active" in error_msg or "ix_employees_employee_id" in error_msg or ("unique constraint" in error_msg and "employee_id" in error_msg):
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This Employee ID is already used.")
        if isinstance(e, HTTPException):
            raise e
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Employee creation failed: {str(e)}")


def update_employee(db: Session, employee_id: int, employee_update: EmployeeUpdate):
    db_employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if db_employee:
        update_data = employee_update.model_dump(exclude_unset=True)
        update_data_keys = set(update_data.keys())
        
        from app.designations.models import Designation as _Designation
        from app.employees.models import EmployeeDesignationHistory
        from app.leave.models import EmployeeLeaveEntitlement, LeaveType as _LeaveType
        from datetime import date as _date

        # Pop designation-specific fields so they never hit setattr on Employee columns that don't exist
        new_designation_id = update_data.pop("designation_id", None)
        designation_start_date = update_data.pop("designation_start_date", None)
        designation_end_date = update_data.pop("designation_end_date", None)
        
        has_leave_overrides = "designation_leave_overrides" in update_data
        designation_leave_overrides_raw = update_data.pop("designation_leave_overrides", None)
        if designation_leave_overrides_raw is None:
            designation_leave_overrides_raw = []
            
        has_accrual_rules = "designation_accrual_rules" in update_data
        designation_accrual_rules_raw = update_data.pop("designation_accrual_rules", None)
        if designation_accrual_rules_raw is None:
            designation_accrual_rules_raw = []

        # Determine current designation state
        resolved_designation_id = new_designation_id if new_designation_id is not None else db_employee.designation_id
        new_designation_str = update_data.get("designation", db_employee.designation)
        
        # Check if designation actually changed
        changed = (
            (new_designation_id is not None and new_designation_id != db_employee.designation_id) or
            ("designation" in update_data and update_data["designation"] != db_employee.designation)
        )

        # Apply basic scalar updates
        for key, value in update_data.items():
            setattr(db_employee, key, value)

        # Sync designation_id FK if provided
        if new_designation_id is not None:
            db_employee.designation_id = new_designation_id
            
        if changed:
            # Resolve the designation string name from the ID
            if resolved_designation_id:
                d = db.query(_Designation).filter(_Designation.id == resolved_designation_id).first()
                if d:
                    new_designation_str = d.name
                    db_employee.designation = d.name
                    db_employee.designation_id = resolved_designation_id
            
            # Close any currently-open history entry
            current_hist = db.query(EmployeeDesignationHistory).filter(
                EmployeeDesignationHistory.employee_id == employee_id,
                EmployeeDesignationHistory.end_date == None
            ).first()
            if current_hist:
                current_hist.end_date = _date.today()
            
            # Create new history entry
            new_hist = EmployeeDesignationHistory(
                employee_id=employee_id,
                designation_id=resolved_designation_id,
                designation_name=new_designation_str or "",
                start_date=designation_start_date or _date.today(),
                end_date=designation_end_date,
                leave_overrides=[e if isinstance(e, dict) else e.model_dump() for e in designation_leave_overrides_raw]
                                 if designation_leave_overrides_raw else None,
            )
            db.add(new_hist)
            db.flush()
        else:
            # If the designation didn't change, we should still update the active history entry's dates/overrides
            current_hist = db.query(EmployeeDesignationHistory).filter(
                EmployeeDesignationHistory.employee_id == employee_id,
                EmployeeDesignationHistory.designation_id == resolved_designation_id
            ).order_by(EmployeeDesignationHistory.created_at.desc()).first()
            
            if current_hist:
                if "designation_start_date" in update_data_keys:
                    current_hist.start_date = designation_start_date
                if "designation_end_date" in update_data_keys:
                    current_hist.end_date = designation_end_date
                if has_leave_overrides:
                    current_hist.leave_overrides = [e if isinstance(e, dict) else e.model_dump() for e in designation_leave_overrides_raw] if designation_leave_overrides_raw else None
            db.flush()

        # Apply leave overrides to EmployeeLeaveEntitlement regardless of whether designation changed
        if has_leave_overrides:
            provided_override_lt_ids = set()
            for override in designation_leave_overrides_raw:
                lt_id = override["leave_type_id"] if isinstance(override, dict) else override.leave_type_id
                lt_days = override["days"] if isinstance(override, dict) else override.days
                provided_override_lt_ids.add(lt_id)
                lt = db.query(_LeaveType).filter(_LeaveType.id == lt_id).first()
                if not lt:
                    continue
                row = db.query(EmployeeLeaveEntitlement).filter(
                    EmployeeLeaveEntitlement.employee_id == employee_id,
                    EmployeeLeaveEntitlement.leave_type_id == lt_id,
                ).first()
                if row:
                    row.days = lt_days
                else:
                    db.add(EmployeeLeaveEntitlement(
                        employee_id=employee_id,
                        leave_type_id=lt_id,
                        days=lt_days,
                    ))
            
            # Delete overrides that are no longer provided
            del_q = db.query(EmployeeLeaveEntitlement).filter(EmployeeLeaveEntitlement.employee_id == employee_id)
            if provided_override_lt_ids:
                del_q = del_q.filter(EmployeeLeaveEntitlement.leave_type_id.notin_(provided_override_lt_ids))
            del_q.delete(synchronize_session=False)

        # Upsert monthly accrual rules if provided
        if has_accrual_rules:
            from app.leave.accrual_models import EmployeeLeaveAccrualRule as _ELAR
            from app.leave.models import LeaveType as _LeaveType2
            from datetime import date as _date2
            _accrual_start = designation_start_date or _date2.today()
            
            provided_accrual_lt_ids = set()
            for rule in designation_accrual_rules_raw:
                lt_id = rule["leave_type_id"] if isinstance(rule, dict) else rule.leave_type_id
                days_pm = rule["days_per_month"] if isinstance(rule, dict) else rule.days_per_month
                provided_accrual_lt_ids.add(lt_id)
                
                if not db.query(_LeaveType2).filter(_LeaveType2.id == lt_id).first():
                    continue
                existing = db.query(_ELAR).filter(
                    _ELAR.employee_id == employee_id,
                    _ELAR.leave_type_id == lt_id,
                ).first()
                if existing:
                    existing.days_per_month = days_pm
                    existing.period_start = _accrual_start
                    existing.period_end = designation_end_date
                    existing.max_carry_forward = None
                    existing.total_leaves_cap = rule.get("total_leaves_cap") if isinstance(rule, dict) else getattr(rule, "total_leaves_cap", None)
                    existing.carry_forward_allowed = rule.get("carry_forward_allowed", False) if isinstance(rule, dict) else getattr(rule, "carry_forward_allowed", False)
                else:
                    db.add(_ELAR(
                        employee_id=employee_id,
                        leave_type_id=lt_id,
                        days_per_month=days_pm,
                        period_start=_accrual_start,
                        period_end=designation_end_date,
                        max_carry_forward=None,
                        total_leaves_cap=rule.get("total_leaves_cap") if isinstance(rule, dict) else getattr(rule, "total_leaves_cap", None),
                        carry_forward_allowed=rule.get("carry_forward_allowed", False) if isinstance(rule, dict) else getattr(rule, "carry_forward_allowed", False),
                    ))
            
            # Delete accrual rules that are no longer provided
            del_accrual_q = db.query(_ELAR).filter(_ELAR.employee_id == employee_id)
            if provided_accrual_lt_ids:
                del_accrual_q = del_accrual_q.filter(_ELAR.leave_type_id.notin_(provided_accrual_lt_ids))
            del_accrual_q.delete(synchronize_session=False)

        if db_employee.user:
            user = db_employee.user
            if "first_name" in update_data: user.first_name = update_data["first_name"]
            if "last_name" in update_data: user.last_name = update_data["last_name"]
            if "email" in update_data:
                user.email = update_data["email"]
                user.username = update_data["email"]
            if "phone" in update_data: user.phone_number = update_data["phone"]
            if "address" in update_data: user.address = update_data["address"]
            if "date_of_birth" in update_data: 
                user.date_of_birth = str(update_data["date_of_birth"]) if update_data["date_of_birth"] else None
            if "emergency_contact_phone" in update_data: user.emergency_contact_number = update_data["emergency_contact_phone"]
            if "employee_id" in update_data: user.employee_id = update_data["employee_id"]
            if "designation" in update_data: user.position = update_data["designation"]
            if "department_id" in update_data:
                db.flush()
                if db_employee.department_rel:
                    user.department = db_employee.department_rel.name

        db.commit()
        db.refresh(db_employee)
    return db_employee


def update_employee_role(db: Session, employee_id: int, role_id: int) -> bool:
    """Assign a new role to an employee (updates their user record)."""
    db_employee = get_employee_by_id(db, employee_id)
    if not db_employee or not db_employee.user:
        return False
        
    from app.roles.models import Role
    role = db.query(Role).filter_by(id=role_id).first()
    if not role:
        return False
        
    user = db_employee.user
    user.role_id = role.id
    user.role = role.role_name
    
    # Update the M:M relationship
    user.roles = [role]
    db.commit()
    return True


def delete_employee(db: Session, employee_id: int) -> bool:
    db_employee = db.query(Employee).filter(Employee.id == employee_id).first()
    if db_employee:
        db_employee.is_deleted = True
        if db_employee.user:
            db_employee.user.is_deleted = True
        db.commit()
        return True
    return False


def resend_login_details(db: Session, employee_id: int, actor: User, background_tasks: BackgroundTasks) -> dict:
    """
    HR action: replace the employee's password with a new temporary one and
    email it again — for a welcome email that never arrived, an expired
    temporary password, or a locked-out employee.

    The old password (temporary or not) stops working immediately and all of
    the employee's sessions are revoked.
    """
    from app.core.config import TEMP_PASSWORD_EXPIRE_DAYS
    from app.auth.models import AuditLog

    db_employee = db.query(Employee).filter(Employee.id == employee_id).first()
    user = db_employee.user if db_employee else None
    if not db_employee or not user:
        raise HTTPException(status_code=404, detail="Employee not found")
    if user.is_active is False:
        raise HTTPException(status_code=400, detail="This account is deactivated. Reactivate it first.")
    # Resetting a super admin's password is itself a privileged act.
    if user.is_superadmin and not actor.is_superadmin:
        raise HTTPException(status_code=403, detail="Only a super admin can reset another super admin's login.")
    if user.id == actor.id:
        raise HTTPException(status_code=400, detail="Use Security Settings to change your own password.")

    temp_password = _issue_temporary_password(user)
    db.add(AuditLog(user_id=user.id, action=f"LOGIN_DETAILS_RESENT_BY:{actor.id}"))
    db.commit()

    full_name = f"{db_employee.first_name} {db_employee.last_name}".strip()
    background_tasks.add_task(
        _email_module.send_welcome_email, user.email, full_name, temp_password,
        expires_days=TEMP_PASSWORD_EXPIRE_DAYS,
    )
    return {
        "message": f"New login details sent to {user.email}. They expire in {TEMP_PASSWORD_EXPIRE_DAYS} days.",
    }


def deactivate_employee(db: Session, employee_id: int) -> dict:
    """Soft-deactivate used by recruitment module."""
    db_employee = get_employee_by_id(db, employee_id)
    if not db_employee:
        raise HTTPException(status_code=404, detail="Employee not found.")
    db_employee.status = "inactive"
    db.commit()
    return {"message": f"Employee {employee_id} deactivated successfully."}


def get_designation_history(db: Session, employee_id: int):
    from app.employees.models import EmployeeDesignationHistory
    return db.query(EmployeeDesignationHistory)\
             .filter(EmployeeDesignationHistory.employee_id == employee_id)\
             .order_by(EmployeeDesignationHistory.start_date.desc())\
             .all()
