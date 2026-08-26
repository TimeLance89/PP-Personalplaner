import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "PP – Personalplaner",
  description: "Ein moderner persönlicher Planer für Aufgaben, Termine und Wochenplanung.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="de">
      <body>{children}</body>
    </html>
  );
}
