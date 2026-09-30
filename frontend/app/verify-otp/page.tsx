"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import AuthLayout from "@/components/auth/AuthLayout";
import { api } from "@/lib/api";
import { useDialog } from "@/context/dialog-context";

export default function VerifyOTP() {

  const router = useRouter();
  const { showAlert } = useDialog();
  const [otp, setOtp] = useState("");
  const [loading, setLoading] = useState(false);

  const handleSubmit = async (e: any) => {
    e.preventDefault();

    const email = sessionStorage.getItem("reset_email");

    if (!email) {
      await showAlert("Email missing. Please restart password reset.", {
        title: "Session expired",
        tone: "warning",
      });
      router.push("/forgot-password");
      return;
    }

    if (!/^\d{6}$/.test(otp)) {
      await showAlert("The verification code is 6 digits.", { title: "Invalid code", tone: "warning" });
      return;
    }

    setLoading(true);

    try {
      await api.post("/auth/verify-otp", { email, otp });
      router.push("/reset-password");
    } catch (err: any) {
      await showAlert(err.message || "Invalid OTP", { title: "Verification failed" });
    }

    setLoading(false);
  };

  return (
    <AuthLayout
      title="Verify OTP"
      description="Enter the verification code sent to your email"
    >
      <form onSubmit={handleSubmit}>

        <input
          type="text"
          placeholder="Enter OTP"
          className="w-full mb-6 px-4 py-3 border border-gray-300 rounded-lg
          text-[#1E293B] placeholder-[#D1D5DC]
          focus:outline-none focus:ring-2 focus:ring-[#F2924E]"
          value={otp}
          onChange={(e) => setOtp(e.target.value.replace(/\D/g, ""))}
          inputMode="numeric"
          autoComplete="one-time-code"
          maxLength={6}
          required
        />

        <button
          type="submit"
          disabled={loading}
          className="w-full bg-[#F2924E] hover:bg-[#e07f3f] text-white py-3 rounded-lg text-[18px] font-semibold transition"
        >
          {loading ? "Verifying..." : "Verify OTP"}
        </button>

        <p
          className="text-[14px] text-[#64748B] hover:text-[#F2924E] mt-6 text-center cursor-pointer transition"
          onClick={() => router.push("/login")}
        >
          Back to Login
        </p>

      </form>
    </AuthLayout>
  );
}