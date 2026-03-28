"use client";

import { useEffect, useState, useRef, useCallback } from "react";
import { cn } from "@/lib/utils";

interface TocItem {
  id: string;
  title: string;
  level: number;
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

export function TableOfContents({ items }: { items: TocItem[] }) {
  const [activeId, setActiveId] = useState<string>("");
  const itemRefs = useRef<Map<string, HTMLLIElement>>(new Map());
  const cancelScrollRef = useRef<(() => void) | null>(null);

  const scrollToItem = useCallback((itemId: string) => {
    const activeItem = itemRefs.current.get(itemId);
    if (!activeItem) return;

    const container = activeItem.closest(".overflow-y-auto") as HTMLElement;
    if (!container) return;

    const containerRect = container.getBoundingClientRect();
    const itemRect = activeItem.getBoundingClientRect();
    const itemTopInContainer = itemRect.top - containerRect.top;

    const threshold = containerRect.height / 6;
    const nearTop = itemTopInContainer < threshold;
    const nearBottom = itemTopInContainer > containerRect.height - threshold;

    if (!nearTop && !nearBottom) return;

    const targetPosition = containerRect.height * 0.33;
    const itemOffsetInContainer = itemTopInContainer + container.scrollTop;
    const targetScrollTop = Math.max(
      0,
      itemOffsetInContainer - targetPosition
    );

    const distance = Math.abs(targetScrollTop - container.scrollTop);
    if (distance < 5) return;

    cancelScrollRef.current?.();
    cancelScrollRef.current = smoothScrollTo(container, targetScrollTop, 450, () => {
      cancelScrollRef.current = null;
    });
  }, []);

  useEffect(() => {
    if (activeId) scrollToItem(activeId);
  }, [activeId, scrollToItem]);

  useEffect(() => {
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

    items.forEach((item) => {
      const element = document.getElementById(item.id);
      if (element) observer.observe(element);
    });

    return () => observer.disconnect();
  }, [items]);

  if (items.length === 0) return null;

  return (
    <nav className="space-y-2">
      <h3 className="mb-3 text-sm font-semibold text-zinc-200">
        On this page
      </h3>
      <ul className="space-y-2 text-sm">
        {items.map((item) => (
          <li
            key={item.id}
            ref={(node) => {
              if (node) itemRefs.current.set(item.id, node);
              else itemRefs.current.delete(item.id);
            }}
            style={{ paddingLeft: `${(item.level - 2) * 12}px` }}
          >
            <a
              href={`#${item.id}`}
              className={cn(
                "block py-1 transition-colors",
                activeId === item.id
                  ? "text-amber-400 font-medium"
                  : "text-zinc-500 hover:text-zinc-200"
              )}
            >
              {item.title}
            </a>
          </li>
        ))}
      </ul>
    </nav>
  );
}
