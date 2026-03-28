import { DocsLayoutClient } from "@/components/docs/docs-layout-client";
import { getDocNavigation } from "@/lib/docs";

export default function DocsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const navigation = getDocNavigation();

  return (
    <DocsLayoutClient navigation={navigation}>{children}</DocsLayoutClient>
  );
}
