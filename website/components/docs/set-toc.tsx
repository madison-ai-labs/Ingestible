"use client";

import { useEffect } from "react";
import { useDocs } from "./docs-context";

interface TocItem {
  id: string;
  title: string;
  level: number;
}

export function SetToc({ items }: { items: TocItem[] }) {
  const { setToc } = useDocs();

  useEffect(() => {
    setToc(items);
    return () => setToc([]);
  }, [items, setToc]);

  return null;
}
