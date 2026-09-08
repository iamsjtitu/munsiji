import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, setToken, setUnauthorizedHandler } from "@/src/api";
import { queryClient } from "@/src/query-client";
import { storage } from "@/src/utils/storage";

const TOKEN_KEY = "munsiji_token";

type AuthState = {
  ready: boolean;
  authed: boolean;
  login: (pin: string) => Promise<void>;
  logout: () => Promise<void>;
};

const AuthContext = createContext<AuthState>({
  ready: false,
  authed: false,
  login: async () => {},
  logout: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);

  const logout = useCallback(async () => {
    setToken(null);
    await storage.secureRemove(TOKEN_KEY);
    queryClient.clear();
    setAuthed(false);
  }, []);

  useEffect(() => {
    setUnauthorizedHandler(() => {
      void logout();
    });
    (async () => {
      const saved = await storage.secureGet<string | null>(TOKEN_KEY, null);
      if (saved) {
        setToken(saved);
        try {
          await api.get("/auth/me");
          setAuthed(true);
        } catch {
          setToken(null);
          await storage.secureRemove(TOKEN_KEY);
        }
      }
      setReady(true);
    })();
  }, [logout]);

  const login = useCallback(async (pin: string) => {
    const data = await api.post<{ access_token: string }>("/auth/login", { pin });
    setToken(data.access_token);
    await storage.secureSet(TOKEN_KEY, data.access_token);
    setAuthed(true);
  }, []);

  const value = useMemo(() => ({ ready, authed, login, logout }), [ready, authed, login, logout]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
