"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import AuthLayout from "@/components/auth/AuthLayout";
import PasswordRequirements from "@/components/auth/PasswordRequirements";
import { Eye, EyeOff } from "lucide-react";
import { api } from "@/lib/api";
import { PASSWORD_MAX_LENGTH, passwordProblem } from "@/lib/passwordPolicy";
import { useDialog } from "@/context/dialog-context";

/** Read once on mount: this page only makes sense straight after a verified OTP. */
const readResetEmail = () =>
  typeof window === "undefined" ? null : sessionStorage.getItem("reset_email");

export default function ResetPassword() {

  const router = useRouter();
  const { showAlert } = useDialog();

  const [email] = useState<string | null>(readResetEmail);
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!email) router.replace("/forgot-password");
  }, [email, router]);

  const handleSubmit = async (e: any) => {
    e.preventDefault();

    const problem = passwordProblem(password, { email });
    if (problem) {
      await showAlert(problem, { title: "Choose a stronger password", tone: "warning" });
      return;
    }

    if (password !== confirm) {
      await showAlert("The two passwords you entered don't match.", {
        title: "Passwords do not match",
        tone: "warning",
      });
      return;
    }

    setLoading(true);

    try {
      await api.post("/auth/reset-password", { email, password });
      sessionStorage.removeItem("reset_email");
      router.push("/reset-success");
    } catch (err: any) {
      await showAlert(err.message || "Failed to reset password", { title: "Couldn't reset password" });
    }

    setLoading(false);
  };

  return (
    <AuthLayout title="Reset Password">

      <form onSubmit={handleSubmit}>

        {/* New Password */}
        <label className="block text-[16px] font-medium text-[#364153] mb-2">
          New Password
        </label>

        <div className="relative mb-6">
          <input
            type={showPassword ? "text" : "password"}
            placeholder="Enter new password"
            autoComplete="new-password"
            maxLength={PASSWORD_MAX_LENGTH}
            className="w-full px-4 py-3 border border-gray-300 rounded-lg
            text-[#1E293B] placeholder-[#D1D5DC]
            focus:outline-none focus:ring-2 focus:ring-[#F2924E]"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />

          <button
            type="button"
            onClick={() => setShowPassword(!showPassword)}
            className="absolute right-4 top-3 text-gray-500 hover:text-gray-700"
          >
            {showPassword ? <EyeOff size={20} /> : <Eye size={20} />}
          </button>
        </div>

        {/* Confirm Password */}
        <label className="block text-[16px] font-medium text-[#364153] mb-2">
          Confirm Password
        </label>

        <div className="relative mb-4">
          <input
            type={showConfirm ? "text" : "password"}
            placeholder="Confirm password"
            autoComplete="new-password"
            maxLength={PASSWORD_MAX_LENGTH}
            className="w-full px-4 py-3 border border-gray-300 rounded-lg
            text-[#1E293B] placeholder-[#D1D5DC]
            focus:outline-none focus:ring-2 focus:ring-[#F2924E]"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />

          <button
            type="button"
            onClick={() => setShowConfirm(!showConfirm)}
            className="absolute right-4 top-3 text-gray-500 hover:text-gray-700"
          >
            {showConfirm ? <EyeOff size={20} /> : <Eye size={20} />}
          </button>
        </div>

        <div className="mb-6">
          <PasswordRequirements password={password} confirm={confirm} email={email} />
        </div>

        <button
          type="submit"
          disabled={loading || !email}
          className="w-full bg-[#F2924E] hover:bg-[#e07f3f] text-white py-3 rounded-lg text-[18px] font-semibold transition"
        >
          {loading ? "Resetting..." : "Reset Password"}
        </button>

      </form>

    </AuthLayout>
  );
}
