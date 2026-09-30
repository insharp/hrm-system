"use client";

import { useState, useEffect } from "react";
import { Lock, Smartphone, Eye, EyeOff, ShieldCheck, AlertCircle } from "lucide-react";
import { apiFetch } from "@/lib/api";
import { useAuth } from "@/context/auth-context";
import PasswordRequirements from "@/components/auth/PasswordRequirements";
import { PASSWORD_MAX_LENGTH, passwordProblem } from "@/lib/passwordPolicy";

export default function SecuritySettingsPage() {
  const { user } = useAuth();
  const personal = { email: user?.email, names: [user?.first_name, user?.last_name] };
  const [passwords, setPasswords] = useState({
    current: "",
    new: "",
    confirm: "",
  });
  const [isUpdatingPass, setIsUpdatingPass] = useState(false);
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [passMsg, setPassMsg] = useState({ text: "", type: "" });

  const [twoFactorEnabled, setTwoFactorEnabled] = useState(false);
  const [setupData, setSetupData] = useState<{secret: string; qr_code_url: string}|null>(null);
  const [verifyCode, setVerifyCode] = useState("");
  const [isSettingUp, setIsSettingUp] = useState(false);
  const [tfaMsg, setTfaMsg] = useState({ text: "", type: "" });
  const [isDisabling, setIsDisabling] = useState(false);
  const [disablePassword, setDisablePassword] = useState("");

  useEffect(() => {
    const fetchUser = async () => {
      try {
        const res = await apiFetch("/auth/me");
        if (res.ok) {
          const data = await res.json();
          setTwoFactorEnabled(data.two_factor_enabled);
        }
      } catch (err) {}
    };
    fetchUser();
  }, []);

  const handlePasswordSave = async (e: React.FormEvent) => {
    e.preventDefault();
    const problem = passwordProblem(passwords.new, personal);
    if (problem) {
      setPassMsg({ text: problem, type: "error" });
      return;
    }
    if (passwords.new !== passwords.confirm) {
      setPassMsg({ text: "New passwords do not match!", type: "error" });
      return;
    }
    if (passwords.new === passwords.current) {
      setPassMsg({ text: "New password must be different from your current password.", type: "error" });
      return;
    }
    setIsUpdatingPass(true);
    setPassMsg({ text: "", type: "" });

    try {
      const res = await apiFetch("/auth/security/password", {
        method: "PUT",
        body: JSON.stringify({
          current_password: passwords.current,
          new_password: passwords.new
        })
      });

      if (res.ok) {
        setPassMsg({ text: "Password updated successfully. Other devices have been signed out.", type: "success" });
        setPasswords({ current: "", new: "", confirm: "" });
        setTimeout(() => setPassMsg({ text: "", type: "" }), 3000);
      } else {
        const errData = await res.json();
        setPassMsg({ text: errData.detail || "Failed to update password", type: "error" });
      }
    } catch (err) {
      console.error(err);
      setPassMsg({ text: "Network error trying to change password.", type: "error" });
    } finally {
      setIsUpdatingPass(false);
    }
  };

  const handleEnableClick = async () => {
    try {
      setTfaMsg({ text: "", type: "" });
      const res = await apiFetch("/auth/security/2fa/setup");
      if (res.ok) {
        const data = await res.json();
        setSetupData(data);
        setIsSettingUp(true);
      } else {
        setTfaMsg({ text: "Failed to start 2FA setup", type: "error" });
      }
    } catch (err) {
      setTfaMsg({ text: "Network error", type: "error" });
    }
  };

  const verifyAndEnable = async () => {
    if (!/^\d{6}$/.test(verifyCode)) {
      setTfaMsg({ text: "Enter the 6-digit code from your authenticator app.", type: "error" });
      return;
    }
    try {
      setTfaMsg({ text: "", type: "" });
      const res = await apiFetch("/auth/security/2fa/verify", {
        method: "POST",
        body: JSON.stringify({ code: verifyCode })
      });
      if (res.ok) {
        setTwoFactorEnabled(true);
        setIsSettingUp(false);
        setSetupData(null);
        setVerifyCode("");
        setTfaMsg({ text: "Two-Factor Authentication enabled successfully!", type: "success" });
        setTimeout(() => setTfaMsg({ text: "", type: "" }), 3000);
      } else {
        const err = await res.json();
        setTfaMsg({ text: err.detail || "Invalid code", type: "error" });
      }
    } catch (err) {
      setTfaMsg({ text: "Network error", type: "error" });
    }
  };

  const handleDisableClick = async () => {
    if (!disablePassword) {
      setTfaMsg({ text: "Enter your password to turn off 2FA.", type: "error" });
      return;
    }
    try {
      const res = await apiFetch("/auth/security/2fa", {
        method: "DELETE",
        body: JSON.stringify({ password: disablePassword }),
      });
      if (res.ok) {
        setTwoFactorEnabled(false);
        setIsDisabling(false);
        setDisablePassword("");
        setTfaMsg({ text: "Two-Factor Authentication disabled.", type: "success" });
        setTimeout(() => setTfaMsg({ text: "", type: "" }), 3000);
      } else {
        const err = await res.json();
        setTfaMsg({ text: err.detail || "Couldn't disable 2FA", type: "error" });
      }
    } catch (err) {
      setTfaMsg({ text: "Network error", type: "error" });
    }
  };

  const inputClass = "w-full border border-gray-200 rounded-xl p-3 text-sm font-medium focus:outline-none focus:ring-2 focus:ring-[#EE7F22]/20 focus:border-[#EE7F22] bg-white transition";
  const labelClass = "block text-sm font-bold text-gray-700 mb-2";

  return (
    <div className="w-full max-h-full pb-10">
      
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 mb-8">
        <div>
          <h2 className="text-2xl font-bold text-gray-900 mb-1">Security Settings</h2>
          <p className="text-gray-400 text-sm font-medium">Manage your password and account security features.</p>
        </div>
      </div>

      <div className="space-y-6">

        {/* Change Password Section */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-50 bg-gray-50/50">
            <h3 className="text-sm font-bold text-gray-800 flex items-center gap-2"><Lock size={16} className="text-[#f08a4b]"/> Change Password</h3>
          </div>
          <div className="p-6">
            <form onSubmit={handlePasswordSave} className="space-y-5">
              
              {passMsg.text && (
                <div className={`p-4 rounded-xl text-sm font-bold border ${passMsg.type === "success" ? "bg-green-50 border-green-100 text-green-700" : "bg-red-50 border-red-100 text-red-600"}`}>
                  {passMsg.text}
                </div>
              )}

              <div className="max-w-xl">
                <label className={labelClass}>Current Password</label>
                <div className="relative">
                  <input 
                    type={showCurrent ? "text" : "password"}
                    value={passwords.current}
                    onChange={(e) => setPasswords({...passwords, current: e.target.value})}
                    autoComplete="current-password"
                    required
                    className={inputClass} 
                  />
                  <button type="button" onClick={() => setShowCurrent(!showCurrent)} className="absolute right-4 top-3.5 text-gray-400 hover:text-[#f08a4b] transition-colors">
                    {showCurrent ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>
              
              <div className="max-w-xl">
                <label className={labelClass}>New Password</label>
                <div className="relative">
                  <input 
                    type={showNew ? "text" : "password"}
                    value={passwords.new}
                    onChange={(e) => setPasswords({...passwords, new: e.target.value})}
                    autoComplete="new-password"
                    maxLength={PASSWORD_MAX_LENGTH}
                    required
                    className={inputClass} 
                  />
                  <button type="button" onClick={() => setShowNew(!showNew)} className="absolute right-4 top-3.5 text-gray-400 hover:text-[#f08a4b] transition-colors">
                    {showNew ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              <div className="max-w-xl">
                <label className={labelClass}>Confirm New Password</label>
                <div className="relative">
                  <input 
                    type={showConfirm ? "text" : "password"}
                    value={passwords.confirm}
                    onChange={(e) => setPasswords({...passwords, confirm: e.target.value})}
                    autoComplete="new-password"
                    maxLength={PASSWORD_MAX_LENGTH}
                    required
                    className={inputClass} 
                  />
                  <button type="button" onClick={() => setShowConfirm(!showConfirm)} className="absolute right-4 top-3.5 text-gray-400 hover:text-[#f08a4b] transition-colors">
                    {showConfirm ? <EyeOff size={16} /> : <Eye size={16} />}
                  </button>
                </div>
              </div>

              {(passwords.new || passwords.confirm) && (
                <div className="max-w-xl">
                  <PasswordRequirements password={passwords.new} confirm={passwords.confirm} {...personal} />
                </div>
              )}

              <div className="pt-4 max-w-xl flex justify-end">
                <button 
                  type="submit"
                  disabled={isUpdatingPass}
                  className="bg-[#f08a4b] hover:bg-[#e07a3b] text-white px-8 py-2.5 rounded-xl text-sm font-bold transition disabled:opacity-50 shadow-md shadow-orange-100 flex items-center justify-center min-w-[150px]"
                >
                  {isUpdatingPass ? (
                    <span className="flex items-center gap-2">
                      <div className="w-4 h-4 border-2 border-white border-t-transparent rounded-full animate-spin"></div>
                      Updating...
                    </span>
                  ) : "Update Password"}
                </button>
              </div>
            </form>
          </div>
        </div>

        {/* Two-Factor Authentication Section */}
        <div className="bg-white rounded-2xl border border-gray-100 shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-50 bg-gray-50/50 flex items-center justify-between">
            <h3 className="text-sm font-bold text-gray-800 flex items-center gap-2"><Smartphone size={16} className="text-[#f08a4b]"/> Two-Factor Authentication</h3>
            {twoFactorEnabled ? (
              <span className="text-[10px] font-bold text-emerald-600 bg-emerald-50 border border-emerald-100 uppercase tracking-wider px-2 py-0.5 rounded-md flex items-center gap-1">
                <ShieldCheck size={12} /> Enabled
              </span>
            ) : (
              <span className="text-[10px] font-bold text-amber-600 bg-amber-50 border border-amber-100 uppercase tracking-wider px-2 py-0.5 rounded-md flex items-center gap-1">
                <AlertCircle size={12} /> Disabled
              </span>
            )}
          </div>
          
          <div className="p-6">
            {tfaMsg.text && (
              <div className={`p-4 mb-6 rounded-xl text-sm font-bold border ${tfaMsg.type === "success" ? "bg-green-50 border-green-100 text-green-700" : "bg-red-50 border-red-100 text-red-600"}`}>
                {tfaMsg.text}
              </div>
            )}

            {!isSettingUp ? (
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-5 rounded-xl border border-gray-100 bg-gray-50/50">
                <div className="flex flex-col sm:flex-row sm:items-center gap-4">
                  <div className="h-12 w-12 bg-white text-[#f08a4b] rounded-full border border-gray-100 shadow-sm flex items-center justify-center font-bold text-sm shrink-0">
                    2FA
                  </div>
                  <div>
                    <h4 className="font-bold text-gray-900 text-sm mb-1">Authenticator App</h4>
                    <p className="text-sm text-gray-500 font-medium">Add an extra layer of security to your account by requiring a code from an authenticator app when you log in.</p>
                  </div>
                </div>
                <div className="shrink-0">
                  {twoFactorEnabled ? (
                    <button 
                      onClick={() => { setIsDisabling(true); setTfaMsg({ text: "", type: "" }); }}
                      className="w-full sm:w-auto px-6 py-2.5 rounded-xl border border-gray-200 text-gray-700 text-sm font-bold hover:bg-gray-100 transition-colors"
                    >
                      Disable 2FA
                    </button>
                  ) : (
                    <button 
                      onClick={handleEnableClick}
                      className="w-full sm:w-auto bg-[#f08a4b] hover:bg-[#e07a3b] text-white px-6 py-2.5 rounded-xl text-sm font-bold transition shadow-md shadow-orange-100"
                    >
                      Enable 2FA
                    </button>
                  )}
                </div>
              </div>
            ) : (
              <div className="border border-gray-100 rounded-xl p-6 bg-gray-50/50">
                <h3 className="font-bold text-gray-900 mb-2">Configure Authenticator App</h3>
                <p className="text-sm text-gray-500 font-medium mb-6">
                  Scan the QR code below with Google Authenticator or Authy, then enter the 6-digit code to verify setup.
                </p>
                {setupData && (
                  <div className="flex flex-col md:flex-row gap-8 mb-8 items-start">
                    <div className="p-3 bg-white border border-gray-200 rounded-xl shadow-sm shrink-0">
                      <img src={setupData.qr_code_url} alt="QR Code" className="w-32 h-32" />
                    </div>
                    <div className="flex flex-col justify-center">
                      <p className="text-sm font-bold text-gray-700 mb-2">Can't scan the QR code?</p>
                      <p className="text-sm text-gray-500 font-medium mb-3">Enter this secret key manually into your authenticator app:</p>
                      <code className="bg-white px-4 py-2.5 border border-gray-200 rounded-xl text-[#f08a4b] font-mono font-bold tracking-widest shadow-sm inline-block">{setupData.secret}</code>
                    </div>
                  </div>
                )}
                <div className="flex flex-col sm:flex-row sm:items-center gap-4 border-t border-gray-100 pt-6">
                  <div className="relative">
                    <input
                      type="text"
                      placeholder="000 000"
                      value={verifyCode}
                      onChange={(e) => setVerifyCode(e.target.value.replace(/\D/g, ""))}
                      inputMode="numeric"
                      autoComplete="one-time-code"
                      maxLength={6}
                      className="w-full sm:w-40 border border-gray-200 rounded-xl p-3 text-center tracking-[0.3em] font-mono font-bold text-gray-900 focus:outline-none focus:ring-2 focus:ring-[#EE7F22]/20 focus:border-[#EE7F22] bg-white transition"
                    />
                  </div>
                  <div className="flex items-center gap-3 w-full sm:w-auto">
                    <button 
                      onClick={verifyAndEnable}
                      className="flex-1 sm:flex-none bg-[#f08a4b] hover:bg-[#e07a3b] text-white px-6 py-3 rounded-xl text-sm font-bold transition shadow-md shadow-orange-100"
                    >
                      Verify & Enable
                    </button>
                    <button 
                      onClick={() => { setIsSettingUp(false); setSetupData(null); setTfaMsg({ text: "", type: "" }); setVerifyCode(""); }}
                      className="px-6 py-3 rounded-xl border border-gray-200 text-gray-700 text-sm font-bold hover:bg-white transition-colors"
                    >
                      Cancel
                    </button>
                  </div>
                </div>
              </div>
            )}
            {isDisabling && twoFactorEnabled && !isSettingUp && (
              <div className="mt-4 p-5 rounded-xl border border-amber-100 bg-amber-50/40 flex flex-col sm:flex-row sm:items-end gap-3">
                <div className="flex-1">
                  <label className={labelClass}>Confirm your password to turn off 2FA</label>
                  <input
                    type="password"
                    autoComplete="current-password"
                    value={disablePassword}
                    onChange={(e) => setDisablePassword(e.target.value)}
                    className={inputClass}
                  />
                </div>
                <div className="flex gap-3">
                  <button
                    onClick={handleDisableClick}
                    className="px-6 py-3 rounded-xl bg-red-500 hover:bg-red-600 text-white text-sm font-bold transition"
                  >
                    Disable 2FA
                  </button>
                  <button
                    onClick={() => { setIsDisabling(false); setDisablePassword(""); }}
                    className="px-6 py-3 rounded-xl border border-gray-200 text-gray-700 text-sm font-bold hover:bg-white transition-colors"
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>

      </div>
    </div>
  );
}
