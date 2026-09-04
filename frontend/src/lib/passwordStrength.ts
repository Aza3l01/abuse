export type PasswordStrength = 0 | 1 | 2 | 3 | 4;

/** Simple client-side strength heuristic — length + character variety. Not a substitute for server-side policy. */
export function passwordStrength(password: string): PasswordStrength {
  let score = 0;
  if (password.length >= 8) score++;
  if (password.length >= 12) score++;
  if (/[a-z]/.test(password) && /[A-Z]/.test(password)) score++;
  if (/[0-9]/.test(password) || /[^A-Za-z0-9]/.test(password)) score++;
  return score as PasswordStrength;
}

export const passwordStrengthLabel: Record<PasswordStrength, string> = {
  0: "Too weak",
  1: "Weak",
  2: "Fair",
  3: "Good",
  4: "Strong",
};
