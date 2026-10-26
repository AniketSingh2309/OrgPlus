import type { Metadata } from "next";
// Inter, self-hosted from the npm package: no request to Google Fonts, at build or in browsers.
import "@fontsource-variable/inter";
import "./globals.css";
import { Providers } from "@/components/providers";

export const metadata: Metadata = {
  title: "Org+",
  description: "Google Workspace org activity dashboard",
  icons: { icon: "/icon.png", apple: "/apple-icon.png" },
};

// Applies the saved theme before first paint (no light flash in dark mode).
const themeScript = `try{var t=localStorage.getItem("orgpulse-theme");var d=t==="dark"||(t!=="light"&&matchMedia("(prefers-color-scheme: dark)").matches);document.documentElement.classList.toggle("dark",d)}catch(e){}`;

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <head>
        <script dangerouslySetInnerHTML={{ __html: themeScript }} />
      </head>
      <body className="min-h-screen font-sans antialiased">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
