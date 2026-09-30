"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import {
  IconArrowLeft,
  IconMail,
  IconPhone,
  IconUserSelect,
  IconBriefcase,
  IconBank,
  IconShieldCheck,
  IconRibbon
} from "@/components/Icons";
import { api } from "@/lib/api";
import { useAuth } from "@/context/auth-context";
import { useDialog } from "@/context/dialog-context";

function DataField({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div>
      <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-[14px] text-gray-800 font-medium">{value || <span className="text-gray-300 italic font-normal">Not provided</span>}</p>
    </div>
  );
}

function DetailCard({ icon, title, children }: { icon: React.ReactNode; title: string; children: React.ReactNode }) {
  return (
    <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
      <div className="px-5 py-4 border-b border-gray-50 flex items-center gap-2.5">
        <div className="text-[#EE7F22]">{icon}</div>
        <h3 className="text-[14px] font-bold text-gray-800">{title}</h3>
      </div>
      <div className="p-5 space-y-4">{children}</div>
    </div>
  );
}

function getInitials(first: string, last: string) {
  return `${(first?.[0] || "").toUpperCase()}${(last?.[0] || "").toUpperCase()}`;
}

interface DesignationHistoryEntry {
  id: number;
  designation_name: string;
  start_date: string;
  end_date: string | null;
  leave_overrides: { leave_type_id: number; days: number }[] | null;
}

interface Employee {
  id: number;
  user_id?: number;
  employee_id: string;
  first_name: string;
  last_name: string;
  email: string;
  phone: string;
  address: string;
  department_id?: number;
  department_rel?: { id: number; name: string };
  designation: string;
  joined_date: string;
  status: string;
  date_of_birth?: string;
  gender?: string;
  marital_status?: string;
  nationality?: string;
  role?: { id: number; role_name: string };
  emergency_contact_name?: string;
  emergency_contact_phone?: string;
  emergency_contact_relation?: string;
  skills?: string;
  qualifications?: string;
  bank_name?: string;
  bank_account_no?: string;
  bank_branch?: string;
}

function EmployeeViewContent() {
  const searchParams = useSearchParams();
  const id = searchParams.get("id");
  const [employee, setEmployee] = useState<Employee | null>(null);
  const [designationHistory, setDesignationHistory] = useState<DesignationHistoryEntry[]>([]);
  const [leaveTypes, setLeaveTypes] = useState<Record<number, string>>({});
  const [loading, setLoading] = useState(true);
  const { user, hasPermission } = useAuth();
  const { showConfirm, showAlert } = useDialog();
  const [resending, setResending] = useState(false);

  /** New temporary password by email; the employee must change it on next login. */
  const resendLoginDetails = async () => {
    if (!employee) return;
    const ok = await showConfirm(
      `${employee.first_name} will get a new temporary password by email. Their current password stops working immediately and they will be signed out everywhere.`,
      { title: "Resend login details?", confirmText: "Send" }
    );
    if (!ok) return;
    setResending(true);
    try {
      const res = await api.post<{ message: string }>(`/employees/${employee.id}/resend-login-details`, {});
      await showAlert(res.message, { title: "Login details sent", tone: "success" });
    } catch (err) {
      await showAlert(err instanceof Error ? err.message : "Couldn't resend login details.", { title: "Not sent" });
    } finally {
      setResending(false);
    }
  };

  useEffect(() => {
    if (!id) return;
    Promise.all([
      api.get<Employee>(`/employees/${id}`),
      api.get<DesignationHistoryEntry[]>(`/employees/${id}/designation-history`),
      api.get<any[]>("/leave/types")
    ])
      .then(([emp, history, types]) => {
        setEmployee(emp);
        setDesignationHistory(history);
        const typeMap = types.reduce((acc, t) => { acc[t.id] = t.name; return acc; }, {} as Record<number, string>);
        setLeaveTypes(typeMap);
      })
      .catch((err) => console.error("Failed to fetch employee details:", err))
      .finally(() => setLoading(false));
  }, [id]);

  if (loading) {
    return (
      <div className="max-w-6xl mx-auto pb-10 space-y-6 animate-pulse">
        <div className="h-36 bg-gray-100 rounded-2xl" />
        <div className="grid grid-cols-2 gap-6">
          <div className="h-56 bg-gray-100 rounded-2xl" />
          <div className="h-56 bg-gray-100 rounded-2xl" />
        </div>
      </div>
    );
  }

  if (!employee) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <div className="w-16 h-16 bg-red-50 rounded-full flex items-center justify-center">
          <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" className="text-red-400" strokeLinecap="round" strokeLinejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
        </div>
        <p className="text-sm font-medium text-gray-600">Employee not found</p>
        <Link href="/dashboard/employees" className="text-sm text-[#EE7F22] hover:underline">← Back to list</Link>
      </div>
    );
  }

  const skills = employee.skills ? employee.skills.split(",").map(s => s.trim()).filter(Boolean) : [];
  const isActive = employee.status === "active";

  return (
    <div className="max-w-6xl mx-auto pb-10">
      {/* Header Nav */}
      <div className="mb-6">
        <Link
          href="/dashboard/employees"
          className="inline-flex items-center gap-1.5 text-sm text-gray-500 hover:text-gray-800 transition-colors mb-5 font-medium group"
        >
          <span className="group-hover:-translate-x-0.5 transition-transform"><IconArrowLeft /></span>
          Back to Employees
        </Link>
      </div>

      {/* Hero Profile Card */}
      <div className="bg-white rounded-xl border border-gray-200 shadow-sm p-6 md:p-8 mb-6">
        <div className="flex flex-col md:flex-row gap-6 items-start md:items-center">
          {/* Avatar */}
          <div className="w-20 h-20 md:w-24 md:h-24 rounded-2xl bg-[#EE7F22] flex items-center justify-center text-white text-2xl md:text-3xl font-bold shadow-lg shadow-orange-200 flex-shrink-0">
            {getInitials(employee.first_name, employee.last_name)}
          </div>

          {/* Core Info */}
          <div className="flex-1 min-w-0">
            <div className="flex flex-wrap items-start gap-3 mb-2">
              <h1 className="text-2xl font-bold text-gray-900">{employee.first_name} {employee.last_name}</h1>
              <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[11px] font-bold tracking-wider border ${
                isActive
                  ? "bg-[#EE7F22]/10 text-[#EE7F22] border-[#F9A15D]/50"
                  : "bg-gray-100 text-gray-500 border-gray-200"
              }`}>
                <span className={`flex-shrink-0 w-1.5 h-1.5 rounded-full ${isActive ? "bg-[#F9A15D]" : "bg-gray-400"}`} />
                <span className="leading-none pt-[1px]">{isActive ? "Active" : "Inactive"}</span>
              </span>
            </div>
            <p className="text-base text-gray-600 mb-0.5">{employee.designation}</p>
            <p className="text-sm text-[#EE7F22] font-semibold mb-4">{employee.department_rel?.name || "No Department"}</p>

            <div className="flex flex-wrap gap-4 text-sm text-gray-500">
              <span className="flex items-center gap-1.5">
                <span className="text-gray-400"><IconMail /></span>
                {employee.email}
              </span>
              <span className="flex items-center gap-1.5">
                <span className="text-gray-400"><IconPhone /></span>
                {employee.phone}
              </span>
              <span className="flex items-center gap-1.5">
                <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-gray-400"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
                <span className="font-mono text-xs bg-gray-100 text-gray-600 px-2 py-0.5 rounded">{employee.employee_id}</span>
              </span>
            </div>
          </div>

          {/* Quick Actions */}
          <div className="flex gap-2 flex-shrink-0">
            {employee.user_id !== user?.id && (
              <Link
                href={`/dashboard/EmployeeManagement/edit?id=${employee.id}`}
                className="inline-flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 rounded-xl text-sm font-semibold text-gray-600 hover:border-orange-300 hover:text-[#EE7F22] transition-all shadow-sm"
              >
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/><path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/></svg>
                Edit
              </Link>
            )}
            {employee.user_id !== user?.id && hasPermission("employee:create") && (
              <button
                type="button"
                onClick={resendLoginDetails}
                disabled={resending}
                className="inline-flex items-center gap-2 px-4 py-2 bg-white border border-gray-200 rounded-xl text-sm font-semibold text-gray-600 hover:border-orange-300 hover:text-[#EE7F22] transition-all shadow-sm disabled:opacity-50"
              >
                <IconMail />
                {resending ? "Sending…" : "Resend login details"}
              </button>
            )}
          </div>
        </div>
      </div>

      {/* Two-column detail grid */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* Left Column */}
        <div className="space-y-5">
          <DetailCard
            icon={<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>}
            title="Personal Information"
          >
            <DataField label="Employee ID" value={<span className="font-mono text-sm">{employee.employee_id}</span>} />
            <DataField label="Date of Birth" value={employee.date_of_birth} />
            <DataField label="Gender" value={employee.gender} />
            <DataField label="Marital Status" value={employee.marital_status} />
            <DataField label="Nationality" value={employee.nationality} />
            <DataField label="Address" value={employee.address} />
          </DetailCard>

          <DetailCard
            icon={<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M22 16.92v3a2 2 0 0 1-2.18 2 19.79 19.79 0 0 1-8.63-3.07A19.5 19.5 0 0 1 4.36 13a19.79 19.79 0 0 1-3.07-8.67A2 2 0 0 1 3.11 2h3a2 2 0 0 1 2 1.72 12.84 12.84 0 0 0 .7 2.81 2 2 0 0 1-.45 2.11L7.91 9.91a16 16 0 0 0 6 6l1.27-1.27a2 2 0 0 1 2.11-.45 12.84 12.84 0 0 0 2.81.7A2 2 0 0 1 22 16.92z"/></svg>}
            title="Emergency Contact"
          >
            <DataField label="Contact Name" value={employee.emergency_contact_name} />
            <DataField label="Relationship" value={employee.emergency_contact_relation} />
            <DataField label="Phone Number" value={employee.emergency_contact_phone} />
          </DetailCard>

          <DetailCard
            icon={<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/></svg>}
            title="Bank Details"
          >
            <DataField label="Bank Name" value={employee.bank_name} />
            <DataField label="Account Number" value={employee.bank_account_no} />
            <DataField label="Branch" value={employee.bank_branch} />
          </DetailCard>
        </div>

        {/* Right Column */}
        <div className="space-y-5">
          <DetailCard
            icon={<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><rect x="2" y="7" width="20" height="14" rx="2" ry="2"/><path d="M16 21V5a2 2 0 0 0-2-2h-4a2 2 0 0 0-2 2v16"/></svg>}
            title="Work Information"
          >
            <DataField label="Department" value={employee.department_rel?.name} />
            <DataField label="Designation" value={employee.designation} />
            <DataField label="Joined Date" value={employee.joined_date} />
            <DataField label="Work Email" value={employee.email} />
            <DataField label="Work Phone" value={employee.phone} />
          </DetailCard>

          <DetailCard
            icon={<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>}
            title="Designation History"
          >
            {designationHistory.length === 0 ? (
              <p className="text-[13px] text-gray-400 italic">No history available</p>
            ) : (
              <div className="relative pl-4 space-y-6 before:absolute before:inset-y-0 before:left-[7px] before:w-0.5 before:bg-gray-100">
                {designationHistory.map((hist, index) => {
                  const isCurrent = !hist.end_date;
                  return (
                    <div key={hist.id} className="relative">
                      <div className={`absolute -left-4 w-2 h-2 rounded-full mt-1.5 ring-4 ring-white ${isCurrent ? "bg-[#EE7F22]" : "bg-gray-300"}`} />
                      <div>
                        <div className="flex items-center gap-2">
                          <p className={`text-[14px] font-bold ${isCurrent ? "text-gray-900" : "text-gray-600"}`}>{hist.designation_name}</p>
                          {isCurrent && <span className="px-2 py-0.5 rounded text-[10px] font-bold bg-[#EE7F22]/10 text-[#EE7F22] uppercase">Current</span>}
                        </div>
                        <p className="text-[12px] text-gray-500 mt-0.5 font-medium">
                          From: {hist.start_date} → {hist.end_date || "Present"}
                        </p>
                        {hist.leave_overrides && hist.leave_overrides.length > 0 ? (
                          <div className="mt-2 bg-gray-50 rounded-lg p-2 border border-gray-100">
                            <p className="text-[10px] font-bold text-gray-400 uppercase tracking-wider mb-1">Leave Overrides</p>
                            <div className="flex flex-wrap gap-x-3 gap-y-1">
                              {hist.leave_overrides.map((override, i) => (
                                <span key={i} className="text-[12px] text-gray-600 font-medium">
                                  {leaveTypes[override.leave_type_id] || `Type ${override.leave_type_id}`}: <span className="text-gray-900">{override.days}d</span>
                                </span>
                              ))}
                            </div>
                          </div>
                        ) : (
                          <p className="text-[11px] text-gray-400 mt-1 italic">Default leave rules</p>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </DetailCard>

          <DetailCard
            icon={<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>}
            title="Skills & Qualifications"
          >
            <div>
              <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-2">Qualifications</p>
              <p className="text-[14px] text-gray-700 whitespace-pre-wrap">
                {employee.qualifications || <span className="text-gray-300 italic font-normal">Not provided</span>}
              </p>
            </div>
            <div>
              <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-2.5">Core Skills</p>
              {skills.length > 0 ? (
                <div className="flex flex-wrap gap-2">
                  {skills.map((skill, i) => (
                    <span key={i} className="px-3 py-1 bg-[#EE7F22]/10 text-orange-700 border border-orange-100 rounded-full text-[12px] font-medium">
                      {skill}
                    </span>
                  ))}
                </div>
              ) : (
                <p className="text-[13px] text-gray-300 italic">Not provided</p>
              )}
            </div>
          </DetailCard>

          <DetailCard
            icon={<svg xmlns="http://www.w3.org/2000/svg" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>}
            title="Role & Permissions"
          >
            <div>
              <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-2">System Role</p>
              {employee.role ? (
                <span className="inline-flex items-center gap-2 px-3 py-1.5 bg-gray-100 text-[#212B36] border border-gray-200 rounded-lg text-sm font-semibold">
                  <svg xmlns="http://www.w3.org/2000/svg" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>
                  {employee.role.role_name}
                </span>
              ) : (
                <span className="inline-flex items-center gap-2 px-3 py-1.5 bg-gray-50 text-gray-400 border border-gray-200 rounded-lg text-sm font-medium italic">
                  No role assigned
                </span>
              )}
            </div>
            <div className="pt-2">
              <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mb-2">Permissions</p>
              <p className="text-[13px] text-gray-400 italic">Permissions are controlled through role assignments.</p>
            </div>
          </DetailCard>
        </div>
      </div>
    </div>
  );
}

export default function EmployeeViewPage() {
  return (
    <React.Suspense fallback={
      <div className="max-w-6xl mx-auto pb-10 space-y-6 animate-pulse">
        <div className="h-8 w-40 bg-gray-100 rounded mb-5" />
        <div className="h-36 bg-gray-100 rounded-2xl" />
        <div className="grid grid-cols-2 gap-5">
          <div className="space-y-5">
            <div className="h-52 bg-gray-100 rounded-2xl" />
            <div className="h-32 bg-gray-100 rounded-2xl" />
          </div>
          <div className="space-y-5">
            <div className="h-52 bg-gray-100 rounded-2xl" />
            <div className="h-44 bg-gray-100 rounded-2xl" />
          </div>
        </div>
      </div>
    }>
      <EmployeeViewContent />
    </React.Suspense>
  );
}
