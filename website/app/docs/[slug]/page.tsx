import { notFound } from "next/navigation";
import { Metadata } from "next";
import {
  getDocBySlug,
  getAllDocSlugs,
  extractTableOfContents,
} from "@/lib/docs";
import { markdownToHtml } from "@/lib/markdown";
import { TableOfContents } from "@/components/docs/table-of-contents";
import { SetToc } from "@/components/docs/set-toc";
import { Breadcrumb } from "@/components/docs/breadcrumb";
import { CodeCopyButtons } from "@/components/docs/code-copy";

interface DocPageProps {
  params: Promise<{ slug: string }>;
}

export async function generateStaticParams() {
  const slugs = getAllDocSlugs();
  return slugs.map((slug) => ({ slug }));
}

export async function generateMetadata({
  params,
}: DocPageProps): Promise<Metadata> {
  const { slug } = await params;
  const doc = getDocBySlug(slug);
  if (!doc) return { title: "Not Found" };

  return {
    title: `${doc.title} | Ingestible Docs`,
    description: `Ingestible documentation — ${doc.title}`,
  };
}

export default async function DocPage({ params }: DocPageProps) {
  const { slug } = await params;
  const doc = getDocBySlug(slug);

  if (!doc) {
    notFound();
  }

  const content = await markdownToHtml(doc.content);
  const toc = extractTableOfContents(doc.content);

  return (
    <div className="flex gap-8 lg:gap-12">
      <SetToc items={toc} />

      {/* Content */}
      <article className="min-w-0 flex-1">
        <Breadcrumb title={doc.title} />
        <div
          className="prose-docs"
          dangerouslySetInnerHTML={{ __html: content }}
        />
        <CodeCopyButtons />
      </article>

      {/* Table of Contents */}
      <aside className="hidden xl:block w-56 flex-shrink-0">
        <div className="sticky top-24 max-h-[calc(100vh-8rem)] overflow-y-auto">
          <TableOfContents items={toc} />
        </div>
      </aside>
    </div>
  );
}
