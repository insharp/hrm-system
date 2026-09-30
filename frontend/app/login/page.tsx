"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import AuthLayout from "@/components/auth/AuthLayout";
import { useAuth } from "@/context/auth-context";
import { apiFetch } from "@/lib/api";
import { Eye, EyeOff } from "lucide-react";

const DASHBOARD_URL = process.env.NEXT_PUBLIC_DASHBOARD_URL ?? "/dashboard";

/** Number of digits in a TOTP / OTP verification code. */
const OTP_CODE_LENGTH = 6;

export default function LoginPage() {
  const router = useRouter();
  const { login } = useAuth();

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [loading, setLoading] = useState(false);

  const [show2FA, setShow2FA] = useState(false);
  const [tempToken, setTempToken] = useState("");
  const [otpCode, setOtpCode] = useState("");
  const [errorMsg, setErrorMsg] = useState("");

  /**
   * Fetches the current user's profile after a successful login
   * and redirects them to the dashboard URL appropriate for their role.
   * Falls back to DASHBOARD_URL if the /auth/me call fails.
   */
  const performRedirect = async () => {
    try {
      const res = await apiFetch("/auth/me");
      if (!res.ok) {
        router.push(DASHBOARD_URL);
        return;
      }
      const userData = await res.json();
      const roleRedirects: Record<string, string> = {
        super_admin: process.env.NEXT_PUBLIC_DASHBOARD_URL ?? "/dashboard",
        hr: process.env.NEXT_PUBLIC_DASHBOARD_URL ?? "/dashboard",
        manager: process.env.NEXT_PUBLIC_DASHBOARD_URL ?? "/dashboard",
        employee: process.env.NEXT_PUBLIC_DASHBOARD_URL ?? "/dashboard",
      };
      router.push(roleRedirects[userData.role] ?? DASHBOARD_URL);
    } catch {
      router.push(DASHBOARD_URL);
    }
  };

  /**
   * Handles the standard login form submission.
   * Sends email/password to the backend; if 2FA is required the form
   * switches to the OTP entry view instead of completing the session.
   * On success, stores the access token and redirects the user.
   */
  const handleLogin = async (e: any) => {
    e.preventDefault();
    setErrorMsg("");
    if (!email.trim() || !password) {
      setErrorMsg("Enter your email or username and password.");
      return;
    }
    setLoading(true);

    try {
      const res = await apiFetch("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email, password }),
      });

      const data = await res.json();

      if (res.ok && data.require_2fa) {
        setTempToken(data.temp_token);
        setShow2FA(true);
        setLoading(false);
        return;
      }

      if (!res.ok) {
        setErrorMsg(data.detail || "Invalid email or password");
        setLoading(false);
        return;
      }

      await login(data.access_token);
      if (data.must_change_password) {
        router.push("/change-password");
      } else {
        await performRedirect();
      }
    } catch (error: any) {
      console.error("Login error:", error);
      setErrorMsg(error.message || "Login failed. Please check backend connection.");
    }

    setLoading(false);
  };

  /**
   * Handles the two-factor authentication form submission.
   * Sends the temp_token (from the initial login response) along with
   * the user's TOTP code to complete authentication and start a session.
   */
  const handle2FASubmit = async (e: any) => {
    e.preventDefault();
    setErrorMsg("");
    if (otpCode.length !== OTP_CODE_LENGTH) {
      setErrorMsg(`Enter the ${OTP_CODE_LENGTH}-digit code from your authenticator app.`);
      return;
    }
    setLoading(true);

    try {
      const res = await apiFetch("/auth/login/2fa", {
        method: "POST",
        body: JSON.stringify({ temp_token: tempToken, code: otpCode }),
      });

      const data = await res.json();

      if (!res.ok) {
        setErrorMsg(data.detail || "Invalid 2FA code");
        setLoading(false);
        return;
      }

      await login(data.access_token);
      if (data.must_change_password) {
        router.push("/change-password");
      } else {
        await performRedirect();
      }
    } catch (error: any) {
      console.error("2FA error:", error);
      setErrorMsg(error.message || "Verification failed.");
    }
    setLoading(false);
  };

  return (
    <AuthLayout
      title="Welcome Back"
      description="Sign in to your HRMS account"
    >
      {!show2FA ? (
        <form onSubmit={handleLogin}>
          {errorMsg && (
            <div className="bg-red-50 text-red-500 text-sm font-medium p-3 rounded-lg mb-4 text-center">
              {errorMsg}
            </div>
          )}

          <label className="block text-[16px] font-medium text-[#364153] mb-2">
            Email or Username
          </label>

          <input
            type="text"
            placeholder="Enter your email or username"
            className="w-full mb-6 px-4 py-3 border border-gray-300 rounded-lg
            text-[#1E293B] placeholder-[#D1D5DC]
            focus:outline-none focus:ring-2 focus:ring-[#F2924E]"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            autoComplete="username"
            maxLength={255}
            required
          />

          <label className="block text-[16px] font-medium text-[#364153] mb-2">
            Password
          </label>

          <div className="relative mb-2">
            <input
              type={showPassword ? "text" : "password"}
              placeholder="Enter your password"
              className="w-full px-4 py-3 border border-gray-300 rounded-lg
              text-[#1E293B] placeholder-[#D1D5DC]
              focus:outline-none focus:ring-2 focus:ring-[#F2924E]"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              maxLength={256}
              required
            />
            <button
              type="button"
              onClick={() => setShowPassword(!showPassword)}
              className="absolute right-4 top-3.5 text-gray-400 hover:text-gray-600 transition-colors"
            >
              {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
            </button>
          </div>

          <p
            className="text-right text-[14px] text-[#F2924E] cursor-pointer mb-6"
            onClick={() => router.push("/forgot-password")}
          >
            Forgot Password?
          </p>

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-[#F2924E] hover:bg-[#e07f3f] text-white py-3 rounded-lg text-[18px] font-semibold transition"
          >
            {loading ? "Logging in..." : "Log In"}
          </button>

          <p className="text-[13px] text-center text-[#64748B] mt-6">
            By continuing, you agree to our{" "}
            <span className="text-[#F2924E] cursor-pointer">
              Terms of Use
            </span>{" "}
            and{" "}
            <span className="text-[#F2924E] cursor-pointer">
              Privacy Policy
            </span>
          </p>

        </form>
      ) : (
        <form onSubmit={handle2FASubmit}>
          <div className="text-center mb-6">
            <h3 className="text-xl font-bold text-gray-900 mb-2">Two-Factor Authentication</h3>
            <p className="text-sm text-gray-500">Enter the 6-digit code from your authenticator app to continue.</p>
          </div>

          {errorMsg && (
            <div className="bg-red-50 text-red-500 text-sm font-medium p-3 rounded-lg mb-4 text-center">
              {errorMsg}
            </div>
          )}

          <label className="block text-[16px] font-medium text-[#364153] mb-2">
            Verification Code
          </label>

          <input
            type="text"
            placeholder="000000"
            className="w-full mb-6 px-4 py-3 border border-gray-300 rounded-lg
            text-center text-2xl tracking-widest text-[#1E293B] placeholder-[#D1D5DC]
            focus:outline-none focus:ring-2 focus:ring-[#F2924E]"
            value={otpCode}
            onChange={(e) => setOtpCode(e.target.value.replace(/\D/g, ""))}
            required
            inputMode="numeric"
            autoComplete="one-time-code"
            pattern={`[0-9]{${OTP_CODE_LENGTH}}`}
            title={`Enter the ${OTP_CODE_LENGTH}-digit code`}
            maxLength={OTP_CODE_LENGTH}
          />

          <button
            type="submit"
            disabled={loading}
            className="w-full bg-[#F2924E] hover:bg-[#e07f3f] text-white py-3 rounded-lg text-[18px] font-semibold transition"
          >
            {loading ? "Verifying..." : "Verify Code"}
          </button>

          <p
            className="text-center text-[14px] text-gray-500 cursor-pointer mt-6 underline"
            onClick={() => setShow2FA(false)}
          >
            Back to login
          </p>
        </form>
      )}
    </AuthLayout>
  );
}