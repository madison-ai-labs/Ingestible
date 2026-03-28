"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { DocsSidebar } from "./sidebar";
import { useDocs } from "./docs-context";
import { cn } from "@/lib/utils";
import type { DocSection } from "@/lib/docs";

interface MobileDocsNavProps {
  navigation: DocSection[];
}

function easeOutQuart(t: number): number {
  return 1 - Math.pow(1 - t, 4);
}

function smoothScrollTo(
  container: HTMLElement,
  targetScrollTop: number,
  duration: number,
  onComplete?: () => void
): () => void {
  const startScrollTop = container.scrollTop;
  const distance = targetScrollTop - startScrollTop;
  const startTime = performance.now();
  let animationId: number;

  function animate(currentTime: number) {
    const elapsed = currentTime - startTime;
    const progress = Math.min(elapsed / duration, 1);
    const eased = easeOutQuart(progress);
    container.scrollTop = startScrollTop + distance * eased;
    if (progress < 1) {
      animationId = requestAnimationFrame(animate);
    } else {
      onComplete?.();
    }
  }

  animationId = requestAnimationFrame(animate);
  return () => cancelAnimationFrame(animationId);
}

export function MobileDocsNav({ navigation }: MobileDocsNavProps) {
  const { toc } = useDocs();
  const [navOpen, setNavOpen] = useState(false);
  const [tocOpen, setTocOpen] = useState(false);
  const [activeId, setActiveId] = useState<string>("");
  const tocItemRefs = useRef<Map<string, HTMLLIElement>>(new Map());
  const cancelScrollRef = useRef<(() => void) | null>(null);

  useEffect(() => {
    if (toc.length === 0) return;

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            setActiveId(entry.target.id);
          }
        });
      },
      { rootMargin: "-80px 0px -80% 0px" }
    );

    toc.forEach((item) => {
      const element = document.getElementById(item.id);
      if (element) observer.observe(element);
    });

    return () => observer.disconnect();
  }, [toc]);

  const scrollToItem = useCallback(
    (itemId: string, force = false, instant = false) => {
      const activeItem = tocItemRefs.current.get(itemId);
      if (!activeItem) return;

      const container = activeItem.closest(".overflow-y-auto") as HTMLElement;
      if (!container) return;

      const containerRect = container.getBoundingClientRect();
      const itemRect = activeItem.getBoundingClientRect();
      const itemTopInContainer = itemRect.top - containerRect.top;

      const threshold = containerRect.height / 6;
      if (
        !force &&
        itemTopInContainer >= threshold &&
        itemTopInContainer <= containerRect.height - threshold
      )
        return;

      const targetPosition = containerRect.height * 0.33;
      const itemOffsetInContainer = itemTopInContainer + container.scrollTop;
      const targetScrollTop = Math.max(
        0,
        itemOffsetInContainer - targetPosition
      );

      if (Math.abs(targetScrollTop - container.scrollTop) < 5) return;

      if (instant) {
        container.scrollTop = targetScrollTop;
      } else {
        cancelScrollRef.current?.();
        cancelScrollRef.current = smoothScrollTo(
          container,
          targetScrollTop,
          450,
          () => {
            cancelScrollRef.current = null;
          }
        );
      }
    },
    []
  );

  useEffect(() => {
    if (tocOpen) {
      requestAnimationFrame(() => {
        const currentActiveId = activeId || toc[0]?.id;
        if (currentActiveId) scrollToItem(currentActiveId, true, true);
      });
    }
  }, [tocOpen, scrollToItem, activeId, toc]);

  useEffect(() => {
    if (tocOpen && activeId) scrollToItem(activeId);
  }, [activeId, tocOpen, scrollToItem]);

  return (
    <>
      {/* Fixed toolbar below header */}
      <div className="lg:hidden fixed top-16 left-0 right-0 z-40 bg-zinc-900/90 backdrop-blur-sm border-b border-zinc-800">
        <div className="flex">
          <button
            type="button"
            onClick={() => setNavOpen(true)}
            className="flex-1 flex items-center justify-center gap-2.5 py-3 text-sm font-medium text-zinc-300 hover:text-zinc-100 hover:bg-zinc-800/50 transition-colors border-r border-zinc-800 min-h-[48px]"
          >
            <svg className="h-4 w-4 text-amber-400" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M19.5 14.25v-2.625a3.375 3.375 0 00-3.375-3.375h-1.5A1.125 1.125 0 0113.5 7.125v-1.5a3.375 3.375 0 00-3.375-3.375H8.25m2.25 0H5.625c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125V11.25a9 9 0 00-9-9z" />
            </svg>
            <span>Navigation</span>
          </button>
          <button
            type="button"
            onClick={() => setTocOpen(true)}
            disabled={toc.length === 0}
            className="flex-1 flex items-center justify-center gap-2.5 py-3 text-sm font-medium text-zinc-300 hover:text-zinc-100 hover:bg-zinc-800/50 transition-colors min-h-[48px] disabled:opacity-40 disabled:cursor-not-allowed"
          >
            <svg className="h-4 w-4 text-amber-400" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 6.75h12M8.25 12h12m-12 5.25h12M3.75 6.75h.007v.008H3.75V6.75zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zM3.75 12h.007v.008H3.75V12zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0zm-.375 5.25h.007v.008H3.75v-.008zm.375 0a.375.375 0 11-.75 0 .375.375 0 01.75 0z" />
            </svg>
            <span>On This Page</span>
          </button>
        </div>
      </div>

      {/* Spacer */}
      <div className="lg:hidden h-[60px]" />

      {/* Left drawer - Navigation */}
      <div
        className={`fixed inset-0 z-[100] lg:hidden transition-[visibility] ${navOpen ? "visible" : "invisible delay-300"}`}
      >
        <div
          className={`absolute inset-0 bg-black transition-opacity duration-300 ${navOpen ? "opacity-40" : "opacity-0"}`}
          onClick={() => setNavOpen(false)}
        />
        <div
          className={`absolute inset-y-0 left-0 w-full max-w-[280px] overflow-y-auto bg-zinc-900 px-5 py-5 ring-1 ring-zinc-800 transition-transform duration-300 ${navOpen ? "translate-x-0" : "-translate-x-full"}`}
        >
          <div className="flex items-center justify-between mb-5">
            <span className="text-base font-semibold text-zinc-100">
              Documentation
            </span>
            <button
              type="button"
              className="p-2 text-zinc-500 hover:text-zinc-100 transition-colors"
              onClick={() => setNavOpen(false)}
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          {navOpen && (
            <DocsSidebar
              navigation={navigation}
              onNavigate={() => setNavOpen(false)}
            />
          )}
        </div>
      </div>

      {/* Right drawer - TOC */}
      <div
        className={`fixed inset-0 z-[100] lg:hidden transition-[visibility] ${tocOpen ? "visible" : "invisible delay-300"}`}
      >
        <div
          className={`absolute inset-0 bg-black transition-opacity duration-300 ${tocOpen ? "opacity-40" : "opacity-0"}`}
          onClick={() => setTocOpen(false)}
        />
        <div
          className={`absolute inset-y-0 right-0 w-full max-w-[280px] overflow-y-auto bg-zinc-900 px-5 py-5 ring-1 ring-zinc-800 transition-transform duration-300 ${tocOpen ? "translate-x-0" : "translate-x-full"}`}
        >
          <div className="flex items-center justify-between mb-5">
            <span className="text-base font-semibold text-zinc-100">
              On This Page
            </span>
            <button
              type="button"
              className="p-2 text-zinc-500 hover:text-zinc-100 transition-colors"
              onClick={() => setTocOpen(false)}
            >
              <svg className="h-5 w-5" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          {toc.length > 0 ? (
            <nav>
              <ul className="space-y-1 text-sm">
                {toc.map((item) => (
                  <li
                    key={item.id}
                    ref={(node) => {
                      if (node) tocItemRefs.current.set(item.id, node);
                      else tocItemRefs.current.delete(item.id);
                    }}
                    style={{ paddingLeft: `${(item.level - 2) * 12}px` }}
                  >
                    <a
                      href={`#${item.id}`}
                      onClick={() => setTocOpen(false)}
                      className={cn(
                        "block py-2 px-2 -mx-2 rounded-md transition-colors",
                        activeId === item.id
                          ? "text-amber-400 bg-amber-400/10 font-medium"
                          : "text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800/50"
                      )}
                    >
                      {item.title}
                    </a>
                  </li>
                ))}
              </ul>
            </nav>
          ) : (
            <p className="text-sm text-zinc-500">No headings on this page.</p>
          )}
        </div>
      </div>
    </>
  );
}
