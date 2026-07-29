import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import type { Role } from "@/core/types";
import {
  isSessionActive,
  sessionLogout,
  sessionRefreshMe,
  sessionUser,
} from "@/data/session";

type SessionStatus = "loading" | "ready";

type SessionContextValue = {
  status: SessionStatus;
  /** The role whose session is currently active, or null when signed out. */
  authedRole: Role | null;
  /** Mark a role as signed in (called after a successful OTP verify). */
  login: (role: Role) => void;
  /** Sign out of the given role and clear its stored tokens. */
  logout: () => Promise<void>;
};

const SessionContext = createContext<SessionContextValue | null>(null);

function isMobileRole(role: string | undefined): role is Role {
  return role === "client" || role === "driver";
}

/**
 * Cold-start auth gate. Client and driver share one mobile token store, so on
 * launch we read the stored user, and if a token exists for a mobile role we
 * validate it against the backend (sessionRefreshMe checks the role matches).
 */
export function SessionProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<SessionStatus>("loading");
  const [authedRole, setAuthedRole] = useState<Role | null>(null);

  useEffect(() => {
    let active = true;
    (async () => {
      const stored = sessionUser("client"); // role-agnostic for mobile store
      if (isSessionActive("client") && isMobileRole(stored?.role)) {
        const me = await sessionRefreshMe(stored.role);
        if (active) setAuthedRole(me ? stored.role : null);
      } else if (active) {
        setAuthedRole(null);
      }
      if (active) setStatus("ready");
    })();
    return () => {
      active = false;
    };
  }, []);

  const login = useCallback((role: Role) => setAuthedRole(role), []);

  const logout = useCallback(async () => {
    const role = authedRole;
    if (role) await sessionLogout(role);
    setAuthedRole(null);
  }, [authedRole]);

  const value = useMemo<SessionContextValue>(
    () => ({ status, authedRole, login, logout }),
    [status, authedRole, login, logout],
  );

  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

export function useSession(): SessionContextValue {
  const ctx = useContext(SessionContext);
  if (!ctx) throw new Error("useSession must be used within <SessionProvider>");
  return ctx;
}
