import { createContext, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { api, DEFAULT_BASE_URL, setBaseUrl, setToken, setUnauthorizedHandler } from "@/src/api";
import { queryClient } from "@/src/query-client";
import { storage } from "@/src/utils/storage";

const TOKEN_KEY = "munsiji_token";
const SERVER_KEY = "munsiji_server_url";

type AuthState = {
  ready: boolean;
  authed: boolean;
  serverUrl: string; // "" = default build URL
  defaultServerUrl: string;
  login: (pin: string) => Promise<void>;
  logout: () => Promise<void>;
  setServerUrl: (url: string) => Promise<void>;
};

const AuthContext = createContext<AuthState>({
  ready: false,
  authed: false,
  serverUrl: "",
  defaultServerUrl: DEFAULT_BASE_URL,
  login: async () => {},
  logout: async () => {},
  setServerUrl: async () => {},
});

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [ready, setReady] = useState(false);
  const [authed, setAuthed] = useState(false);
  const [serverUrl, setServerUrlState] = useState("");

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
      const savedServer = (await storage.getItem<string>(SERVER_KEY, "")) ?? "";
      setBaseUrl(savedServer || null);
      setServerUrlState(savedServer);
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

  const setServerUrl = useCallback(
    async (url: string) => {
      const clean = url.trim().replace(/\/+$/, "");
      if (clean && !/^https:\/\/[^\s/]+/i.test(clean) && !/^http:\/\/(localhost|127\.0\.0\.1|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.)/i.test(clean)) {
        throw new Error("Server URL https:// se shuru hona chahiye");
      }
      await storage.setItem(SERVER_KEY, clean);
      setBaseUrl(clean || null);
      setServerUrlState(clean);
      await logout();
    },
    [logout],
  );

  const value = useMemo(
    () => ({ ready, authed, serverUrl, defaultServerUrl: DEFAULT_BASE_URL, login, logout, setServerUrl }),
    [ready, authed, serverUrl, login, logout, setServerUrl],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}
