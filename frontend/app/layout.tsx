import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Sora } from "next/font/google";

import "./globals.css";
import { Providers } from "@/components/providers";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter" });
const sora = Sora({ subsets: ["latin"], variable: "--font-sora" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains" });

export const metadata: Metadata = {
  title: "Quackfix",
  description: "AI Incident Resolution Portal",
  icons: {
    icon: "/assets/logo_light_mode.png",
    apple: "/assets/logo_light_mode.png",
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={`${inter.variable} ${sora.variable} ${jetbrains.variable}`}>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
