import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { ArchiveNotice } from "@/components/archive-notice";
import { SiteFooter } from "@/components/site-footer";
import { TopNav } from "@/components/top-nav";
import { ARCHIVE_MODE } from "@/lib/archive-mode";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const viewport: Viewport = {
  themeColor: "#07090c",
  colorScheme: "dark",
};

export const metadata: Metadata = {
  title: "Fin-Sentry",
  description:
    "Fin-Sentry guards the question, the retrieved text and the answer, scores delivered answers with a two-tier judge and reconstructs failures with an evidence-bounded agent that abstains when the records fall short. The reference workload is financial RAG over SEC filings, and recorded Red Team and agent runs can be inspected.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col">
        <a
          href="#main-content"
          className="bg-accent text-background sr-only rounded-md px-4 py-2 font-medium focus-visible:not-sr-only focus-visible:absolute focus-visible:top-2 focus-visible:left-2 focus-visible:z-[60]"
        >
          Skip to content
        </a>
        <TopNav />
        {ARCHIVE_MODE ? <ArchiveNotice /> : null}
        <main id="main-content" className="flex flex-1 flex-col">
          {children}
        </main>
        <SiteFooter />
      </body>
    </html>
  );
}
