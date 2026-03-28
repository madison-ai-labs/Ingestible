"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { cn } from "@/lib/utils";
import type { DocSection } from "@/lib/docs";

interface DocsSidebarProps {
  navigation: DocSection[];
  onNavigate?: () => void;
}

export function DocsSidebar({ navigation, onNavigate }: DocsSidebarProps) {
  const pathname = usePathname();
  const currentSlug = pathname.split("/").pop();
  const activeRef = useRef<HTMLAnchorElement>(null);
  const [filterQuery, setFilterQuery] = useState("");

  const filteredNavigation = filterQuery.trim()
    ? navigation
        .map((section) => ({
          ...section,
          items: section.items.filter((item) =>
            item.title.toLowerCase().includes(filterQuery.toLowerCase())
          ),
        }))
        .filter((section) => section.items.length > 0)
    : navigation;

  useEffect(() => {
    if (activeRef.current && !filterQuery) {
      const container = activeRef.current.closest(
        '[class*="overflow-y"]'
      ) as HTMLElement;
      if (container) {
        const containerRect = container.getBoundingClientRect();
        const activeRect = activeRef.current.getBoundingClientRect();
        const scrollOffset =
          activeRect.top -
          containerRect.top -
          containerRect.height / 2 +
          activeRect.height / 2;
        container.scrollTop = scrollOffset;
      }
    }
  }, [filterQuery]);

  return (
    <div className="flex flex-col h-full">
      <div className="relative mb-4">
        <svg
          className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-zinc-500 pointer-events-none"
          fill="none"
          viewBox="0 0 24 24"
          strokeWidth={1.5}
          stroke="currentColor"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            d="M21 21l-5.197-5.197m0 0A7.5 7.5 0 105.196 5.196a7.5 7.5 0 0010.607 10.607z"
          />
        </svg>
        <input
          type="text"
          value={filterQuery}
          onChange={(e) => setFilterQuery(e.target.value)}
          placeholder="Filter..."
          className="w-full pl-9 pr-3 py-2 text-sm rounded-lg bg-zinc-800/50 border border-zinc-700/50 text-zinc-100 placeholder:text-zinc-500 focus:outline-none focus:ring-2 focus:ring-amber-400/50 focus:border-amber-400/50 transition-colors"
        />
        {filterQuery && (
          <button
            onClick={() => setFilterQuery("")}
            className="absolute right-2 top-1/2 -translate-y-1/2 p-1 text-zinc-500 hover:text-zinc-100 transition-colors"
          >
            <svg className="h-3.5 w-3.5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        )}
      </div>

      <nav className="space-y-6 flex-1">
        {filteredNavigation.length === 0 ? (
          <p className="text-sm text-zinc-500 px-3 py-2">
            No results for &ldquo;{filterQuery}&rdquo;
          </p>
        ) : (
          filteredNavigation.map((section) => (
            <div key={section.title}>
              <h3 className="mb-2 text-sm font-semibold text-zinc-200">
                {section.title}
              </h3>
              <ul className="space-y-1">
                {section.items.map((item) => {
                  const isActive =
                    currentSlug === item.slug ||
                    (currentSlug === "docs" && item.slug === "Introduction");

                  return (
                    <li key={item.slug}>
                      <Link
                        ref={isActive ? activeRef : undefined}
                        href={`/docs/${item.slug}`}
                        onClick={onNavigate}
                        className={cn(
                          "flex items-center gap-2 rounded-md px-3 py-2 text-sm transition-colors",
                          isActive
                            ? "bg-amber-400/10 text-amber-400 font-medium"
                            : "text-zinc-400 hover:bg-zinc-800/50 hover:text-zinc-100"
                        )}
                      >
                        {isActive && (
                          <svg className="h-3 w-3" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
                          </svg>
                        )}
                        <span className={!isActive ? "ml-5" : ""}>
                          {item.title}
                        </span>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          ))
        )}
      </nav>
    </div>
  );
}
