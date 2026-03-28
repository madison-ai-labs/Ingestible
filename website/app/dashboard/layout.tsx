import dynamic from "next/dynamic";

export const metadata = {
  title: "Dashboard | Ingestible",
};

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <div className="pt-16 min-h-screen">{children}</div>;
}
