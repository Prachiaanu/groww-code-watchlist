import type { Metadata } from "next";

import "./globals.css";

export const metadata: Metadata = {
  title: "Smart Market Watchlist",
  description: "Track stocks and instantly see what meaningfully changed since you last looked.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
