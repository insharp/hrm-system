"use client";

import { useState, useEffect } from "react";
import { User, Upload, Mail, Hash, Briefcase, Edit2, X, Phone, MapPin, Calendar, CreditCard, Award, HeartPulse } from "lucide-react";
import { apiFetch, fileUrl, formatApiError } from "@/lib/api";

const InfoItem = ({ label, value, icon: Icon }: { label: string, value: string, icon?: any }) => (
  <div className="flex flex-col p-4 bg-gray-50/50 rounded-xl border border-gray-100 h-full">
    <div className="flex items-center gap-1.5 mb-2">
      {Icon && <Icon size={14} className="text-[#f08a4b]" />}
      <span className="text-[11px] font-bold text-gray-400 uppercase tracking-wider">{label}</span>
    </div>
    <span className="text-sm font-semibold text-gray-800 break-words whitespace-pre-wrap">{value || "—"}</span>
  </div>
);

export default function ProfileSettingsPage() {

  const [isEditing, setIsEditing] = useState(false);
  const [originalData, setOriginalData] = useState<any>(null);

  const [formData, setFormData] = useState({
    // Editable
    first_name: "",
    last_name: "",
    phone_number: "",
    address: "",
    date_of_birth: "",
    gender: "",
    marital_status: "",
    nationality: "",
    emergency_contact_name: "",
    emergency_contact_number: "", // Legacy User field mapped to phone
    emergency_contact_relation: "",
    bank_name: "",
    bank_account_no: "",
    bank_branch: "",
    skills: "",
    qualifications: "",
    // Read-only display
    employee_id: "",
    department: "",
    email: "",
    profile_image_url: "",
    designation: "",
    joined_date: "",
    status: "",
    role: "", 
    designation_history: [] as Array<{
      designation_name: string;
      start_date: string | null;
      end_date: string | null;
    }>,
  });

  const [isLoading, setIsLoading] = useState(false);
  const [msg, setMsg] = useState({ text: "", type: "" });
  const [historyExpanded, setHistoryExpanded] = useState(false);

  useEffect(() => {
    const fetchProfile = async () => {
      try {
        const res = await apiFetch("/auth/me");
        if (res.ok) {
          const data = await res.json();
          const parsedData = {
            first_name: data.first_name || "",
            last_name: data.last_name || "",
            employee_id: data.employee_id || "",
            department: data.department || "",
            email: data.email || "",
            phone_number: data.phone_number || "",
            address: data.address || "",
            date_of_birth: data.date_of_birth || "",
            gender: data.gender || "",
            marital_status: data.marital_status || "",
            nationality: data.nationality || "",
            emergency_contact_name: data.emergency_contact_name || "",
            emergency_contact_number: data.emergency_contact_number || "",
            emergency_contact_relation: data.emergency_contact_relation || "",
            bank_name: data.bank_name || "",
            bank_account_no: data.bank_account_no || "",
            bank_branch: data.bank_branch || "",
            skills: data.skills || "",
            qualifications: data.qualifications || "",
            profile_image_url: data.profile_image_url || "",
            designation: data.designation || "",
            joined_date: data.joined_date || "",
            status: data.status || "",
            role: data.role || "",
            designation_history: data.designation_history || [],
          };
          setFormData(parsedData);
          setOriginalData(parsedData);
        }
      } catch (err) {
        console.error("Failed to fetch profile", err);
      }
    };
    fetchProfile();
  }, []);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement | HTMLTextAreaElement>) => {
    setFormData({ ...formData, [e.target.name]: e.target.value });
  };

  const handleCancel = () => {
    if (originalData) setFormData(originalData);
    setIsEditing(false);
    setMsg({ text: "", type: "" });
  };

  /**
   * True when the user edited this field. Only edited fields are validated and
   * sent, so data saved before the validation rules existed (e.g. an old phone
   * format) never blocks saving an unrelated change.
   */
  const isChanged = (key: keyof typeof formData) => !originalData || formData[key] !== originalData[key];

  /** Mirrors backend UserProfileUpdate validation so mistakes show instantly. */
  const validateProfile = (): string | null => {
    const nameRe = /^[\p{L}]+(?:[ .'\-]+[\p{L}]+)*\.?$/u;
    const phoneRe = /^\+?[0-9\s\-()]{7,15}$/;
    const first = formData.first_name.trim();
    const last = formData.last_name.trim();
    if (isChanged("first_name") && !first) return "First name is required.";
    if (isChanged("last_name") && !last) return "Last name is required.";
    if ((isChanged("first_name") && !nameRe.test(first)) || (isChanged("last_name") && !nameRe.test(last))) {
      return "Names may only contain letters, spaces, apostrophes, dots and hyphens.";
    }
    if (isChanged("phone_number") && formData.phone_number.trim() && !phoneRe.test(formData.phone_number.trim())) {
      return "Please enter a valid phone number.";
    }
    if (isChanged("emergency_contact_number") && formData.emergency_contact_number.trim() && !phoneRe.test(formData.emergency_contact_number.trim())) {
      return "Please enter a valid emergency contact number.";
    }
    if (isChanged("emergency_contact_name") && formData.emergency_contact_name.trim() && !nameRe.test(formData.emergency_contact_name.trim())) {
      return "Emergency contact name may only contain letters, spaces, apostrophes, dots and hyphens.";
    }
    if (isChanged("bank_account_no") && formData.bank_account_no.trim() && !/^[0-9 \-]{4,50}$/.test(formData.bank_account_no.trim())) {
      return "Bank account number may only contain digits, spaces and dashes.";
    }
    if (isChanged("date_of_birth") && formData.date_of_birth) {
      const today = new Date();
      const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
      if (formData.date_of_birth > todayStr) return "Date of birth cannot be in the future.";
      if (formData.date_of_birth < "1900-01-01") return "Please enter a realistic date of birth.";
    }
    return null;
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const problem = validateProfile();
    if (problem) {
      setMsg({ text: problem, type: "error" });
      return;
    }
    setIsLoading(true);
    setMsg({ text: "", type: "" });

    const allFields = {
      first_name: formData.first_name,
      last_name: formData.last_name,
      phone_number: formData.phone_number,
      address: formData.address,
      date_of_birth: formData.date_of_birth,
      gender: formData.gender,
      marital_status: formData.marital_status,
      nationality: formData.nationality,
      emergency_contact_name: formData.emergency_contact_name,
      emergency_contact_number: formData.emergency_contact_number,
      emergency_contact_relation: formData.emergency_contact_relation,
      bank_name: formData.bank_name,
      bank_account_no: formData.bank_account_no,
      bank_branch: formData.bank_branch,
      skills: formData.skills,
      qualifications: formData.qualifications,
    };
    // Send only what was edited (the backend applies partial updates).
    const payload = Object.fromEntries(
      Object.entries(allFields).filter(([key]) => isChanged(key as keyof typeof formData))
    );

    try {
      const res = await apiFetch("/auth/profile", {
        method: "PUT",
        body: JSON.stringify(payload)
      });

      if (res.ok) {
        setOriginalData(formData);
        setIsEditing(false);
        setMsg({ text: "Profile updated successfully!", type: "success" });
        setTimeout(() => setMsg({ text: "", type: "" }), 3500);
      } else {
        const errData = await res.json();
        setMsg({ text: formatApiError(errData.detail, "Failed to update profile"), type: "error" });
      }
    } catch (err) {
      console.error(err);
      setMsg({ text: "Network error saving profile", type: "error" });
    } finally {
      setIsLoading(false);
    }
  };

  const handleImageUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const file = e.target.files[0];
    const data = new FormData();
    data.append("file", file);

    try {
      const res = await apiFetch("/auth/profile/image", { method: "POST", body: data });
      if (res.ok) {
        const result = await res.json();
        setFormData(prev => ({ ...prev, profile_image_url: result.profile_image_url }));
        setOriginalData((prev: any) => ({ ...prev, profile_image_url: result.profile_image_url }));
        setMsg({ text: "Profile photo uploaded!", type: "success" });
        setTimeout(() => setMsg({ text: "", type: "" }), 3000);
      } else {
        setMsg({ text: "Failed to upload photo.", type: "error" });
      }
    } catch (err) {
      setMsg({ text: "Network error during upload.", type: "error" });
    }
  };

  const inputClass = "w-full border border-gray-200 rounded-xl p-3 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-[#EE7F22]/20 focus:border-[#EE7F22] bg-white transition";
  const labelClass = "block text-sm font-bold text-gray-700 mb-2";

  return (
    <div className="w-full max-h-full pb-10">
      
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 mb-1">Personal Information</h2>
          <p className="text-gray-400 text-sm font-medium">Manage your personal details, emergency contacts, and more.</p>
        </div>
        {!isEditing && (
          <button
            onClick={() => setIsEditing(true)}
            className="flex items-center gap-2 bg-[#f08a4b] hover:bg-[#e07a3b] text-white px-5 py-2.5 rounded-xl text-sm font-bold transition shadow-sm shadow-orange-100"
          >
            <Edit2 size={15} />
            Edit Profile
          </button>
        )}
      </div>

      <div className="space-y-6">
          {msg.text && (
            <div className={`p-4 rounded-xl text-sm font-bold border ${msg.type === "success" ? "bg-green-50 border-green-100 text-green-700" : "bg-red-50 border-red-100 text-red-600"}`}>
              {msg.text}
            </div>
          )}

          {/* Avatar Section */}
          <div className="bg-white p-6 rounded-2xl border border-gray-100 shadow-sm flex flex-col sm:flex-row sm:items-center gap-6">
            <div className="h-28 w-28 bg-gray-50 rounded-full flex items-center justify-center text-gray-300 shadow-inner overflow-hidden border border-gray-100 shrink-0 relative group">
              {formData.profile_image_url ? (
                <img src={fileUrl(formData.profile_image_url)} alt="Profile" className="w-full h-full object-cover" />
              ) : (
                <User size={48} className="mt-2 text-gray-300" />
              )}
              <label className="absolute inset-0 bg-black/40 flex flex-col items-center justify-center text-white opacity-0 group-hover:opacity-100 cursor-pointer transition-opacity backdrop-blur-[2px]">
                <Upload size={20} className="mb-1" />
                <span className="text-[10px] font-bold uppercase tracking-wide">Upload</span>
                <input type="file" className="hidden" accept="image/*" onChange={handleImageUpload} />
              </label>
            </div>
            <div className="flex-1">
              <h3 className="text-xl font-bold text-gray-900 mb-1">{formData.first_name} {formData.last_name}</h3>
              <p className="text-[#f08a4b] font-semibold text-sm mb-3">{formData.designation || "No Designation"}</p>
              
              <div className="flex flex-wrap gap-3 text-sm text-gray-500 font-medium">
                {formData.employee_id && <span className="flex items-center gap-1.5 bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-100"><Hash size={14}/> {formData.employee_id}</span>}
                {formData.department && <span className="flex items-center gap-1.5 bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-100"><Briefcase size={14}/> {formData.department}</span>}
                {formData.email && <span className="flex items-center gap-1.5 bg-gray-50 px-3 py-1.5 rounded-lg border border-gray-100"><Mail size={14}/> {formData.email}</span>}
              </div>
            </div>
            
            {!isEditing && (
              <div className="hidden sm:block">
                <label className="inline-flex items-center gap-2 bg-gray-50 hover:bg-gray-100 text-gray-700 border border-gray-200 px-4 py-2 rounded-xl text-xs font-bold transition cursor-pointer">
                  <Upload size={14} />
                  Change Photo
                  <input type="file" className="hidden" accept="image/*" onChange={handleImageUpload} />
                </label>
              </div>
            )}
          </div>

          {!isEditing ? (
            /* ======================= READ-ONLY VIEW ======================= */
            <div className="space-y-6">
              
              {/* Basic Information */}
              <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-50 bg-gray-50/50">
                  <h3 className="text-sm font-bold text-gray-800 flex items-center gap-2"><User size={16} className="text-[#f08a4b]"/> Basic Details</h3>
                </div>
                <div className="p-6 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  <InfoItem label="First Name" value={formData.first_name} />
                  <InfoItem label="Last Name" value={formData.last_name} />
                  <InfoItem label="Phone Number" value={formData.phone_number} icon={Phone} />
                  <InfoItem label="Date of Birth" value={formData.date_of_birth} icon={Calendar} />
                  <InfoItem label="Gender" value={formData.gender} />
                  <InfoItem label="Marital Status" value={formData.marital_status} />
                  <div className="md:col-span-2 lg:col-span-3">
                    <InfoItem label="Home Address" value={formData.address} icon={MapPin} />
                  </div>
                </div>
              </div>

              {/* Work Details & History */}
              <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-50 bg-gray-50/50 flex items-center justify-between">
                  <h3 className="text-sm font-bold text-gray-800 flex items-center gap-2"><Briefcase size={16} className="text-[#f08a4b]"/> Work Profile</h3>
                  <span className="text-[10px] font-bold text-gray-400 uppercase tracking-wider bg-gray-100 px-2 py-0.5 rounded-md">Admin Assigned</span>
                </div>
                <div className="p-6">
                  <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4 mb-6">
                    <InfoItem label="Employee ID" value={formData.employee_id} />
                    <InfoItem label="Department" value={formData.department} />
                    <InfoItem label="Role" value={formData.role} />
                    <InfoItem label="Designation" value={formData.designation} />
                    <InfoItem label="Joined Date" value={formData.joined_date} icon={Calendar} />
                    <InfoItem label="Status" value={formData.status} />
                  </div>

                  {formData.designation_history.length > 0 && (
                    <div className="mt-6">
                      <button
                        type="button"
                        onClick={() => setHistoryExpanded(!historyExpanded)}
                        className="w-full flex items-center justify-between group p-4 hover:bg-gray-50 rounded-xl transition-colors border border-gray-100"
                      >
                        <div className="flex items-center gap-2">
                          <h4 className="text-sm font-bold text-gray-800">Designation History</h4>
                          <span className="text-[11px] text-[#f08a4b] font-bold bg-orange-50 px-2 py-0.5 rounded-full border border-orange-100">
                            {formData.designation_history.length} Entries
                          </span>
                        </div>
                        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" className={`text-gray-400 group-hover:text-[#f08a4b] transition-transform duration-200 ${historyExpanded ? "rotate-180" : "rotate-0"}`}>
                          <polyline points="6 9 12 15 18 9" />
                        </svg>
                      </button>

                      <div
                        style={{
                          maxHeight: historyExpanded ? "800px" : "0px",
                          opacity: historyExpanded ? 1 : 0,
                          overflow: "hidden",
                          transition: "max-height 0.4s cubic-bezier(0.4,0,0.2,1), opacity 0.3s ease",
                        }}
                      >
                        <div className="mt-3 space-y-3 px-1 pb-1">
                          {formData.designation_history.map((hist, idx) => (
                            <div key={idx} className="flex flex-col sm:flex-row sm:items-center justify-between p-4 rounded-xl bg-gray-50/50 border border-gray-100">
                              <div className="flex items-center gap-3">
                                <div className="w-10 h-10 rounded-full bg-white shadow-sm text-[#f08a4b] border border-gray-100 flex items-center justify-center shrink-0">
                                  <Briefcase size={16} />
                                </div>
                                <div>
                                  <p className="text-sm font-bold text-gray-900">{hist.designation_name}</p>
                                  <p className="text-[11px] font-bold text-gray-400 uppercase tracking-wider mt-0.5">
                                    {hist.start_date ? new Date(hist.start_date).toLocaleDateString() : 'N/A'} — {hist.end_date ? new Date(hist.end_date).toLocaleDateString() : 'Present'}
                                  </p>
                                </div>
                              </div>
                              {idx === 0 && !hist.end_date && (
                                <span className="mt-3 sm:mt-0 text-[10px] font-bold uppercase tracking-wider text-emerald-600 bg-emerald-50 border border-emerald-100 px-3 py-1 rounded-full w-fit shrink-0">
                                  Current Role
                                </span>
                              )}
                            </div>
                          ))}
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* Emergency Contact */}
                <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden h-full">
                  <div className="px-6 py-4 border-b border-gray-50 bg-gray-50/50">
                    <h3 className="text-sm font-bold text-gray-800 flex items-center gap-2"><HeartPulse size={16} className="text-[#f08a4b]"/> Emergency Contact</h3>
                  </div>
                  <div className="p-6 grid grid-cols-1 gap-4">
                    <InfoItem label="Contact Name" value={formData.emergency_contact_name} />
                    <InfoItem label="Relationship" value={formData.emergency_contact_relation} />
                    <InfoItem label="Contact Phone" value={formData.emergency_contact_number} icon={Phone} />
                  </div>
                </div>

                {/* Bank Details */}
                <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden h-full">
                  <div className="px-6 py-4 border-b border-gray-50 bg-gray-50/50">
                    <h3 className="text-sm font-bold text-gray-800 flex items-center gap-2"><CreditCard size={16} className="text-[#f08a4b]"/> Bank Details</h3>
                  </div>
                  <div className="p-6 grid grid-cols-1 gap-4">
                    <InfoItem label="Bank Name" value={formData.bank_name} />
                    <InfoItem label="Account Number" value={formData.bank_account_no} />
                    <InfoItem label="Branch Name" value={formData.bank_branch} />
                  </div>
                </div>
              </div>

              {/* Skills & Qualifications */}
              <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-50 bg-gray-50/50">
                  <h3 className="text-sm font-bold text-gray-800 flex items-center gap-2"><Award size={16} className="text-[#f08a4b]"/> Skills & Qualifications</h3>
                </div>
                <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-4">
                  <InfoItem label="Skills" value={formData.skills} />
                  <InfoItem label="Qualifications" value={formData.qualifications} />
                </div>
              </div>

            </div>
          ) : (
            /* ======================= EDIT MODE FORM ======================= */
            <form onSubmit={handleSave} className="space-y-6">
              
              <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-50 bg-gray-50/50">
                  <h3 className="text-sm font-bold text-gray-800 flex items-center gap-2"><User size={16} className="text-[#f08a4b]"/> Basic Details</h3>
                </div>
                <div className="p-6 grid grid-cols-1 md:grid-cols-2 gap-x-8 gap-y-5">
                  <div>
                    <label className={labelClass}>First Name</label>
                    <input name="first_name" type="text" maxLength={100} value={formData.first_name} onChange={handleChange} className={inputClass} />
                  </div>
                  <div>
                    <label className={labelClass}>Last Name</label>
                    <input name="last_name" type="text" maxLength={100} value={formData.last_name} onChange={handleChange} className={inputClass} />
                  </div>
                  <div>
                    <label className={labelClass}>Phone Number</label>
                    <input name="phone_number" type="text" maxLength={20} value={formData.phone_number} onChange={handleChange} placeholder="+1 (555) 000-0000" className={inputClass} />
                  </div>
                  <div>
                    <label className={labelClass}>Date of Birth</label>
                    <input name="date_of_birth" type="date" min="1900-01-01" value={formData.date_of_birth} onChange={handleChange} className={inputClass} />
                  </div>
                  <div>
                    <label className={labelClass}>Gender</label>
                    <select name="gender" value={formData.gender} onChange={handleChange} className={inputClass}>
                      <option value="">Select gender</option>
                      <option value="Male">Male</option>
                      <option value="Female">Female</option>
                      <option value="Other">Other</option>
                      <option value="Prefer not to say">Prefer not to say</option>
                    </select>
                  </div>
                  <div>
                    <label className={labelClass}>Marital Status</label>
                    <select name="marital_status" value={formData.marital_status} onChange={handleChange} className={inputClass}>
                      <option value="">Select status</option>
                      <option value="Single">Single</option>
                      <option value="Married">Married</option>
                      <option value="Divorced">Divorced</option>
                      <option value="Widowed">Widowed</option>
                    </select>
                  </div>
                  <div className="md:col-span-2">
                    <label className={labelClass}>Nationality</label>
                    <input name="nationality" type="text" maxLength={100} value={formData.nationality} onChange={handleChange} placeholder="e.g. Sri Lankan" className={inputClass} />
                  </div>
                  <div className="md:col-span-2">
                    <label className={labelClass}>Home Address</label>
                    <input name="address" type="text" maxLength={500} value={formData.address} onChange={handleChange} placeholder="Enter your full address" className={inputClass} />
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden h-full">
                  <div className="px-6 py-4 border-b border-gray-50 bg-gray-50/50">
                    <h3 className="text-sm font-bold text-gray-800 flex items-center gap-2"><HeartPulse size={16} className="text-[#f08a4b]"/> Emergency Contact</h3>
                  </div>
                  <div className="p-6 space-y-5">
                    <div>
                      <label className={labelClass}>Contact Name</label>
                      <input name="emergency_contact_name" type="text" maxLength={100} value={formData.emergency_contact_name} onChange={handleChange} placeholder="Contact name" className={inputClass} />
                    </div>
                    <div>
                      <label className={labelClass}>Relationship</label>
                      <input name="emergency_contact_relation" type="text" maxLength={50} value={formData.emergency_contact_relation} onChange={handleChange} placeholder="e.g. Spouse, Parent" className={inputClass} />
                    </div>
                    <div>
                      <label className={labelClass}>Contact Phone</label>
                      <input name="emergency_contact_number" type="text" maxLength={20} value={formData.emergency_contact_number} onChange={handleChange} placeholder="Emergency phone number" className={inputClass} />
                    </div>
                  </div>
                </div>

                <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden h-full">
                  <div className="px-6 py-4 border-b border-gray-50 bg-gray-50/50">
                    <h3 className="text-sm font-bold text-gray-800 flex items-center gap-2"><CreditCard size={16} className="text-[#f08a4b]"/> Bank Details</h3>
                  </div>
                  <div className="p-6 space-y-5">
                    <div>
                      <label className={labelClass}>Bank Name</label>
                      <input name="bank_name" type="text" maxLength={100} value={formData.bank_name} onChange={handleChange} placeholder="Bank name" className={inputClass} />
                    </div>
                    <div>
                      <label className={labelClass}>Account Number</label>
                      <input name="bank_account_no" type="text" maxLength={50} value={formData.bank_account_no} onChange={handleChange} placeholder="Account number" className={inputClass} />
                    </div>
                    <div>
                      <label className={labelClass}>Branch Name</label>
                      <input name="bank_branch" type="text" maxLength={100} value={formData.bank_branch} onChange={handleChange} placeholder="Branch name" className={inputClass} />
                    </div>
                  </div>
                </div>
              </div>

              <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
                <div className="px-6 py-4 border-b border-gray-50 bg-gray-50/50">
                  <h3 className="text-sm font-bold text-gray-800 flex items-center gap-2"><Award size={16} className="text-[#f08a4b]"/> Skills & Qualifications</h3>
                </div>
                <div className="p-6 space-y-5">
                  <div>
                    <label className={labelClass}>Skills</label>
                    <textarea name="skills" maxLength={2000} value={formData.skills} onChange={handleChange} placeholder="List skills separated by commas (e.g., JavaScript, React, SQL)" className={`${inputClass} min-h-[100px] resize-none`} />
                  </div>
                  <div>
                    <label className={labelClass}>Qualifications</label>
                    <textarea name="qualifications" maxLength={2000} value={formData.qualifications} onChange={handleChange} placeholder="Enter educational qualifications and certifications" className={`${inputClass} min-h-[100px] resize-none`} />
                  </div>
                </div>
              </div>

              <div className="mt-8 flex items-center justify-end gap-3">
                <button
                  type="button"
                  onClick={handleCancel}
                  className="px-6 py-2.5 rounded-xl border border-gray-200 text-gray-700 text-sm font-bold hover:bg-gray-50 transition-colors"
                >
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={isLoading}
                  className="bg-[#f08a4b] hover:bg-[#e07a3b] text-white px-8 py-2.5 rounded-xl text-sm font-bold transition disabled:opacity-50 shadow-md shadow-orange-100 flex items-center justify-center min-w-[150px]"
                >
                  {isLoading ? (
                    <span className="flex items-center gap-2">
                      <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                      Saving...
                    </span>
                  ) : "Save Changes"}
                </button>
              </div>
            </form>
          )}
      </div>
    </div>
  );
}
