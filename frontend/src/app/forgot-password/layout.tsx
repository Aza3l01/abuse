import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "Reset your password",
  description: "Enter your email address and we'll send you a link to reset your Clew password.",
};

export default function ForgotPasswordLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
