"use client";

import { createContext, useContext, useEffect, useState, useCallback, useRef } from "react";
import { usePathname, useRouter } from "next/navigation";
import { apiFetch, getToken, removeToken, setToken, handleRefreshFlow, refreshAccessToken, CHANGE_PASSWORD_PATH } from "@/lib/api";

// ── Module-level constants ──────────────────────────────────────────────────────
/** How often the background token refresh fires (minutes). */
const TOKEN_REFRESH_INTERVAL_MINUTES = 13;
/** Minimum gap between two consecutive refresh calls (minutes). Prevents overlap. */
const MIN_REFRESH_GUARD_MINUTES = 10;

export interface User {
  id: number;
  email: string;
  username?: string;
  is_active: boolean;
  is_superadmin?: boolean;   // explicit DB flag — not derived from role name
  role: string;
  role_id?: number;
  position?: string;
  permissions: string[];
  first_name?: string;
  last_name?: string;
  employee_id?: string;
  department?: string;
  profile_image_url?: string;
  two_factor_enabled?: boolean;
  /** True until a new employee replaces their emailed temporary password. */
  must_change_password?: boolean;
  notification_preferences?: Record<string, { email: boolean; inApp: boolean }>;
  // Days to keep notifications; null/undefined = never auto-delete.
  notification_retention_days?: number | null;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  login: (token: string) => Promise<void>;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
  hasPermission: (perm: string) => boolean;
  hasAnyPermission: (perms: string[]) => boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);
  const pathname = usePathname();
  const router = useRouter();

  /**
   * Fetches the current user's profile from /auth/me.
   *
   * Strategy:
   * 1. Try the access token already in sessionStorage.
   * 2. If none exists (page reload, new tab, hot-reload wiped sessionStorage),
   *    silently exchange the HttpOnly refresh-token cookie for a new access
   *    token BEFORE giving up. This is what prevents the "15-min logout" bug.
   * 3. Only treat the user as logged-out if the refresh also fails.
   */
  const fetchUser = useCallback(async () => {
    let token = getToken();

    // No token in sessionStorage — try a silent cookie-based refresh first.
    // IMPORTANT: only do this if we have a tab-scoped user ID stamp, meaning
    // this tab previously had a valid session. Without the stamp a fresh tab
    // would absorb whatever cookie another tab left behind (cross-tab hijack).
    if (!token) {
      const tabUserId = sessionStorage.getItem("hrm_tab_uid");
      if (!tabUserId) {
        // Brand-new tab with no prior session — don't attempt a cookie refresh.
        setLoading(false);
        return;
      }
      try {
        token = await refreshAccessToken();
      } catch {
        sessionStorage.removeItem("hrm_tab_uid");
        setLoading(false);
        return;
      }
    }

    try {
      const res = await apiFetch("/auth/me");
      if (!res.ok) throw new Error("Unauthorized");
      const data = await res.json();

      // Cross-tab identity check: if this tab was previously logged in as user X
      // but the cookie refresh returned user Y (another tab logged in and replaced
      // the shared cookie), abort and clear this tab rather than silently swapping.
      const tabUserId = sessionStorage.getItem("hrm_tab_uid");
      if (tabUserId && String(data.id) !== tabUserId) {
        console.warn("Auth: tab user mismatch — cookie belongs to a different session. Clearing tab.");
        removeToken();
        sessionStorage.removeItem("hrm_tab_uid");
        setUser(null);
        setLoading(false);
        return;
      }

      // Stamp the user ID for future cross-tab checks
      sessionStorage.setItem("hrm_tab_uid", String(data.id));
      setUser({ ...data, permissions: data.permissions ?? [] });
    } catch (e) {
      console.error("Auth error:", e);
      removeToken();
      sessionStorage.removeItem("hrm_tab_uid");
      setUser(null);
    } finally {
      setLoading(false);
    }
  }, []);


  const lastRefreshTimeRef = useRef<number>(Date.now());

  /**
   * First login with an emailed temporary password: keep the user on the
   * change-password screen until they set their own. (The API refuses every
   * other call anyway — this just avoids a screen full of errors.)
   */
  useEffect(() => {
    if (user?.must_change_password && pathname !== CHANGE_PASSWORD_PATH) {
      router.replace(CHANGE_PASSWORD_PATH);
    }
  }, [user, pathname, router]);

  /** Runs once on mount to restore the user session from the stored access token. */
  useEffect(() => { 
    fetchUser(); 
  }, [fetchUser]);

  /** Re-fetch user on every route change to ensure permissions are instantly up-to-date. */
  useEffect(() => {
    // Only re-fetch if we are already authenticated (don't force a fetch for guests)
    if (getToken()) {
      fetchUser();
    }
  }, [pathname, fetchUser]);

  /**
   * Silently refreshes the access token every 13 minutes via the HttpOnly
   * refresh-token cookie. A guard prevents overlapping refreshes if one
   * occurred within the last 10 minutes. Redirects to /login on failure.
   */
  useEffect(() => {
    // Silent background refresh every 13 minutes (780,000 ms)
    const interval = setInterval(async () => {
      const now = Date.now();
      
      // Guard: Do not allow another refresh if one happened in the last 10 minutes
      if (now - lastRefreshTimeRef.current < MIN_REFRESH_GUARD_MINUTES * 60 * 1000) {
        return;
      }

      const token = getToken();
      if (token) {
        try {
          lastRefreshTimeRef.current = now;
          await handleRefreshFlow();
        } catch (e) {
          console.error("Background token refresh failed:", e);
        }
      }
    }, TOKEN_REFRESH_INTERVAL_MINUTES * 60 * 1000);

    return () => clearInterval(interval);
  }, []);

  /**
   * Stores the access token in sessionStorage (per-tab isolation) and
   * immediately fetches the user profile to populate the auth context.
   */
  const login = async (token: string) => {
    setLoading(true);
    setUser(null);
    setToken(token);
    // Temporarily clear any stale tab UID so fetchUser stamps a fresh one
    sessionStorage.removeItem("hrm_tab_uid");
    await fetchUser();
  };

  const logout = async () => {
    try {
      await apiFetch("/auth/logout", { method: "POST" });
    } catch (e) {
      console.error("Logout API error:", e);
    }
    removeToken();
    sessionStorage.removeItem("hrm_tab_uid");
    window.location.href = "/login";
  };

  /**
   * Forces a re-fetch of the user profile from the backend.
   * Useful after profile updates so the UI reflects the latest data.
   */
  const refreshUser = async () => { 
    setLoading(true);
    await fetchUser(); 
  };

  /** Returns true if the current user holds the exact permission string. */
  const hasPermission = (perm: string): boolean =>
    user?.permissions?.includes(perm) ?? false;

  /** Returns true if the current user holds at least one of the given permission strings. */
  const hasAnyPermission = (perms: string[]): boolean =>
    perms.some((p) => user?.permissions?.includes(p));

  return (
    <AuthContext.Provider value={{ user, loading, login, logout, refreshUser, hasPermission, hasAnyPermission }}>
      {children}
    </AuthContext.Provider>
  );
}

/**
 * Custom hook to consume the AuthContext.
 * Must be used inside an <AuthProvider> — throws a descriptive error otherwise.
 */
export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}