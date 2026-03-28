"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  ReactNode,
} from "react";
import { AuthConfig, getAuth, setAuth, clearAuth } from "@/lib/api";

interface AuthContextType {
  auth: AuthConfig | null;
  isLoading: boolean;
  login: (config: AuthConfig) => void;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [auth, setAuthState] = useState<AuthConfig | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    setAuthState(getAuth());
    setIsLoading(false);
  }, []);

  const login = useCallback((config: AuthConfig) => {
    setAuth(config);
    setAuthState(config);
  }, []);

  const logout = useCallback(() => {
    clearAuth();
    setAuthState(null);
  }, []);

  return (
    <AuthContext.Provider value={{ auth, isLoading, login, logout }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
