"use client";

import { ReactNode } from "react";
import { DocsProvider } from "./docs-context";
import { MobileDocsNav } from "./mobile-nav";
import { DocsSidebar } from "./sidebar";
import type { DocSection } from "@/lib/docs";

interface DocsLayoutClientProps {
  navigation: DocSection[];
  children: ReactNode;
}

function DocsLayoutContent({ navigation, children }: DocsLayoutClientProps) {
  return (
    <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
      <MobileDocsNav navigation={navigation} />

      <div className="flex gap-8 lg:gap-12 py-6 lg:py-10">
        {/* Desktop Sidebar */}
        <aside className="hidden lg:block w-64 flex-shrink-0">
          <div className="sticky top-24 overflow-y-auto max-h-[calc(100vh-8rem)] pr-4">
            <DocsSidebar navigation={navigation} />
          </div>
        </aside>

        {/* Main content */}
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

export function DocsLayoutClient({
  navigation,
  children,
}: DocsLayoutClientProps) {
  return (
    <DocsProvider>
      <DocsLayoutContent navigation={navigation}>
        {children}
      </DocsLayoutContent>
    </DocsProvider>
  );
}
