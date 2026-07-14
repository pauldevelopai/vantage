// Authentication helpers for the console.
//
// The token + user are stored in localStorage by LoginPage (keys
// `alibi_token` / `alibi_user`). This module centralises reading them and the
// role-based access checks the pages use (hasRole / canPerformAction).
//
// Roles (from the backend): 'operator' | 'supervisor' | 'admin'. Operators
// observe; supervisors and admins can act on incidents. This mirrors the
// human-in-the-loop safety model — operators never dispatch on their own.

const TOKEN_KEY = 'alibi_token';
const USER_KEY = 'alibi_user';

export interface AuthUser {
  username: string;
  role: string;
  full_name?: string;
}

/** JWT for the Authorization header (or null when signed out). */
export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

/** The signed-in user, or null. */
export function getUser(): AuthUser | null {
  const raw = localStorage.getItem(USER_KEY);
  if (!raw || raw === 'undefined' || raw === 'null') return null;
  try {
    return JSON.parse(raw) as AuthUser;
  } catch {
    return null;
  }
}

/** True when a token is present. */
export function isAuthenticated(): boolean {
  return !!getToken();
}

/** Clear credentials and return to the login screen. */
export function logout(): void {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(USER_KEY);
  window.location.href = '/login';
}

/**
 * Whether the current user has (one of) the given role(s). Exact match — the
 * pages combine explicitly, e.g. hasRole('supervisor') || hasRole('admin').
 */
export function hasRole(role: string | string[]): boolean {
  const user = getUser();
  if (!user) return false;
  const roles = Array.isArray(role) ? role : [role];
  return roles.includes(user.role);
}

// Which actions each role may take on an incident.
const ROLE_ACTIONS: Record<string, string[]> = {
  operator: ['view'],
  supervisor: ['view', 'acknowledge', 'confirm', 'dismiss', 'dispatch'],
  admin: ['view', 'acknowledge', 'confirm', 'dismiss', 'dispatch', 'manage'],
};

/** Whether the current user is permitted to perform an incident action. */
export function canPerformAction(action: string): boolean {
  const user = getUser();
  if (!user) return false;
  return (ROLE_ACTIONS[user.role] || []).includes(action);
}
