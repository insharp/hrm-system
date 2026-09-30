/**
 * passwordPolicy.ts — client-side mirror of backend/app/core/password_policy.py.
 *
 * Used for live feedback only; the backend is the authority and re-checks
 * everything. Keep the two files in sync.
 */

export const PASSWORD_MIN_LENGTH = 8;
export const PASSWORD_MAX_LENGTH = 72; // bcrypt hashes at most 72 bytes
const SPECIAL_CHARS = "!@#$%^&*()_+-=[]{};':\"\\|,.<>/?`~";

export interface PasswordRule {
  id: string;
  label: string;
  test: (pw: string) => boolean;
}

export const PASSWORD_RULES: PasswordRule[] = [
  {
    id: "length",
    label: `${PASSWORD_MIN_LENGTH}–${PASSWORD_MAX_LENGTH} characters`,
    test: (pw) =>
      pw.length >= PASSWORD_MIN_LENGTH && new TextEncoder().encode(pw).length <= PASSWORD_MAX_LENGTH,
  },
  { id: "upper", label: "An uppercase letter (A–Z)", test: (pw) => /[A-Z]/.test(pw) },
  { id: "lower", label: "A lowercase letter (a–z)", test: (pw) => /[a-z]/.test(pw) },
  { id: "number", label: "A number (0–9)", test: (pw) => /\d/.test(pw) },
  {
    id: "special",
    label: "A special character (e.g. ! @ # $ %)",
    test: (pw) => [...pw].some((ch) => SPECIAL_CHARS.includes(ch)),
  },
  { id: "spaces", label: "No leading or trailing spaces", test: (pw) => pw.length > 0 && pw === pw.trim() },
];

/** True when the password contains the email's local part or a name (3+ chars). */
export function containsPersonalInfo(pw: string, email?: string | null, names: (string | null | undefined)[] = []): boolean {
  const lowered = pw.toLowerCase();
  const parts = [email ? email.split("@")[0] : null, ...names];
  return parts.some((p) => {
    const part = (p ?? "").trim().toLowerCase();
    return part.length >= 3 && lowered.includes(part);
  });
}

/** Returns the first problem to show the user, or null if the password passes. */
export function passwordProblem(
  pw: string,
  opts: { email?: string | null; names?: (string | null | undefined)[] } = {}
): string | null {
  const failed = PASSWORD_RULES.find((r) => !r.test(pw));
  if (failed) return `Password needs: ${failed.label.toLowerCase()}.`;
  if (containsPersonalInfo(pw, opts.email, opts.names)) {
    return "Password must not contain your name or email address.";
  }
  return null;
}
