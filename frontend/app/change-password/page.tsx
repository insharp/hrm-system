"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { Eye, EyeOff } from "lucide-react";
import AuthLayout from "@/components/auth/AuthLayout";
import PasswordRequirements from "@/components/auth/PasswordRequirements";
import { useAuth } from "@/context/auth-context";
import { apiFetch, setToken } from "@/lib/api";
import { PASSWORD_MAX_LENGTH, passwordProblem } from "@/lib/passwordPolicy";

const DASHBOARD_URL = process.env.NEXT_PUBLIC_DASHBOARD_URL ?? "/dashboard";

/**
 * Mandatory first-login screen. A new employee signs in with the temporary
 * password from the welcome email and must replace it here before the rest of
 * the app (and API) becomes available.
 */
export default function ChangePasswordPage() {
  const router = useRouter();
  const { user, loading, refreshUser, logout } = useAuth();

  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [errorMsg, setErrorMsg] = useState("");

  // Only meaningful for a signed-in user who still has a pending change.
  useEffect(() => {
    if (loading) return;
    if (!user) router.replace("/login");
    else if (!user.must_change_password) router.replace(DASHBOARD_URL);
  }, [user, loading, router]);

  const names = [user?.first_name, user?.last_name];

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setErrorMsg("");

    const problem = passwordProblem(password, { email: user?.email, names });
    if (problem) return setErrorMsg(problem);
    if (password !== confirm) return setErrorMsg("The two passwords don't match.");

    setSubmitting(true);
    try {
      const res = await apiFetch("/auth/first-login/password", {
        method: "POST",
        body: JSON.stringify({ new_password: password, confirm_password: confirm }),
      });
      const data = await res.json();
      if (!res.ok) {
        setErrorMsg(typeof data.detail === "string" ? data.detail : "Couldn't update your password.");
        return;
      }
      // The backend rotated the session; use the fresh access token.
      setToken(data.access_token);
      await refreshUser();
      router.replace(DASHBOARD_URL);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Couldn't update your password. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (loading || !user?.must_change_password) {
    return <div className="min-h-screen flex items-center justify-center text-gray-500">Loading...</div>;
  }

  const inputClass =
    "w-full px-4 py-3 border border-gray-300 rounded-lg text-[#1E293B] placeholder-[#D1D5DC] focus:outline-none focus:ring-2 focus:ring-[#F2924E]";

  return (
    <AuthLayout
      title="Set Your Password"
      description="For your security, replace the temporary password from your welcome email before continuing."
    >
      <form onSubmit={handleSubmit} noValidate>
        {errorMsg && (
          <div className="bg-red-50 text-red-500 text-sm font-medium p-3 rounded-lg mb-4 text-center" role="alert">
            {errorMsg}
          </div>
        )}

        <label className="block text-[16px] font-medium text-[#364153] mb-2" htmlFor="new-password">
          New Password
        </label>
        <div className="relative mb-4">
          <input
            id="new-password"
            type={showPassword ? "text" : "password"}
            autoComplete="new-password"
            placeholder="Enter a new password"
            className={inputClass}
            value={password}
            maxLength={PASSWORD_MAX_LENGTH}
            onChange={(e) => setPassword(e.target.value)}
            required
            autoFocus
          />
          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            className="absolute right-4 top-3.5 text-gray-400 hover:text-gray-600"
            aria-label={showPassword ? "Hide password" : "Show password"}
          >
            {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
          </button>
        </div>

        <label className="block text-[16px] font-medium text-[#364153] mb-2" htmlFor="confirm-password">
          Confirm New Password
        </label>
        <div className="relative mb-4">
          <input
            id="confirm-password"
            type={showConfirm ? "text" : "password"}
            autoComplete="new-password"
            placeholder="Re-enter the new password"
            className={inputClass}
            value={confirm}
            maxLength={PASSWORD_MAX_LENGTH}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
          <button
            type="button"
            onClick={() => setShowConfirm(!showConfirm)}
            className="absolute right-4 top-3.5 text-gray-400 hover:text-gray-600"
            aria-label={showConfirm ? "Hide password" : "Show password"}
          >
            {showConfirm ? <EyeOff size={20} /> : <Eye size={20} />}
          </button>
        </div>

        <div className="mb-6">
          <PasswordRequirements password={password} confirm={confirm} email={user.email} names={names} />
        </div>

        <button
          type="submit"
          disabled={submitting}
          className="w-full bg-[#F2924E] hover:bg-[#e07f3f] text-white py-3 rounded-lg text-[18px] font-semibold transition disabled:opacity-60"
        >
          {submitting ? "Saving..." : "Set Password & Continue"}
        </button>

        <p
          className="text-[14px] text-[#64748B] hover:text-[#F2924E] mt-6 text-center cursor-pointer transition"
          onClick={() => logout()}
        >
          Not you? Sign out
        </p>
      </form>
    </AuthLayout>
  );
}
