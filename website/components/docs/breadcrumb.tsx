import Link from "next/link";

export function Breadcrumb({ title }: { title: string }) {
  return (
    <nav aria-label="Breadcrumb" className="mb-6">
      <ol className="flex items-center gap-2 text-sm">
        <li>
          <Link
            href="/"
            className="text-zinc-500 hover:text-amber-400 transition-colors"
          >
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" d="M2.25 12l8.954-8.955c.44-.439 1.152-.439 1.591 0L21.75 12M4.5 9.75v10.125c0 .621.504 1.125 1.125 1.125H9.75v-4.875c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125V21h4.125c.621 0 1.125-.504 1.125-1.125V9.75M8.25 21h8.25" />
            </svg>
          </Link>
        </li>
        <li>
          <svg className="h-4 w-4 text-zinc-600" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
        </li>
        <li>
          <Link
            href="/docs/Introduction"
            className="text-zinc-500 hover:text-amber-400 transition-colors"
          >
            Docs
          </Link>
        </li>
        <li>
          <svg className="h-4 w-4 text-zinc-600" fill="none" viewBox="0 0 24 24" strokeWidth={2} stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" d="M8.25 4.5l7.5 7.5-7.5 7.5" />
          </svg>
        </li>
        <li>
          <span className="text-zinc-100 font-medium truncate max-w-[200px]">
            {title}
          </span>
        </li>
      </ol>
    </nav>
  );
}
