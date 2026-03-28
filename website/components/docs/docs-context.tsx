"use client";

import {
  createContext,
  useContext,
  useState,
  useEffect,
  useCallback,
  ReactNode,
} from "react";

interface TocItem {
  id: string;
  title: string;
  level: number;
}

interface DocsContextType {
  toc: TocItem[];
  setToc: (items: TocItem[]) => void;
}

const DocsContext = createContext<DocsContextType | undefined>(undefined);

export function DocsProvider({ children }: { children: ReactNode }) {
  const [toc, setToc] = useState<TocItem[]>([]);

  return (
    <DocsContext.Provider value={{ toc, setToc }}>
      {children}
    </DocsContext.Provider>
  );
}

export function useDocs() {
  const context = useContext(DocsContext);
  if (!context) {
    throw new Error("useDocs must be used within a DocsProvider");
  }
  return context;
}
