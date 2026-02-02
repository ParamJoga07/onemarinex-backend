// src/services/authService.ts
export type UserRole = "shipping_company" | "vendor" | "agent";

export interface SignupPayload {
  name?: string | null;
  email: string;
  password: string;
  role: UserRole; // <— NEW
}

export interface SignupResponse {
  id: number;
  name: string | null;
  email: string;
  role: UserRole;
}

export interface LoginPayload {
  email: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  role: UserRole; // <— NEW
}

const API_BASE = (import.meta as any).env?.VITE_API_BASE || "http://localhost:8000";

async function http<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  let data: any = null;
  try { data = await res.json(); } catch {}
  if (!res.ok) {
    const msg = data?.detail || data?.message || `${res.status} ${res.statusText}`;
    throw new Error(typeof msg === "string" ? msg : "Request failed");
  }
  return data as T;
}

export const authService = {
  signup(payload: SignupPayload) {
    return http<SignupResponse>("/api/v1/auth/signup", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
  login(payload: LoginPayload) {
    return http<LoginResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
};
