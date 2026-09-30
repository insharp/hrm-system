"use client";

import { Check, X } from "lucide-react";
import { PASSWORD_RULES, containsPersonalInfo } from "@/lib/passwordPolicy";

interface Props {
  password: string;
  confirm?: string;
  email?: string | null;
  names?: (string | null | undefined)[];
}

/** Live checklist of the password policy, ticking rules off as the user types. */
export default function PasswordRequirements({ password, confirm, email, names }: Props) {
  const items = PASSWORD_RULES.map((r) => ({ label: r.label, ok: r.test(password) }));
  if (email || names?.length) {
    items.push({
      label: "Doesn't contain your name or email",
      ok: password.length > 0 && !containsPersonalInfo(password, email, names),
    });
  }
  if (confirm !== undefined) {
    items.push({ label: "Both passwords match", ok: password.length > 0 && password === confirm });
  }

  return (
    <ul className="space-y-1 text-[13px]" aria-live="polite">
      {items.map((item) => (
        <li
          key={item.label}
          className={`flex items-center gap-2 ${item.ok ? "text-emerald-600" : "text-gray-400"}`}
        >
          {item.ok ? <Check size={14} /> : <X size={14} />}
          {item.label}
        </li>
      ))}
    </ul>
  );
}
