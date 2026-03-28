import fs from "fs";
import path from "path";
import matter from "gray-matter";

const docsDirectory = path.join(process.cwd(), "content/docs");

export interface DocPage {
  slug: string;
  title: string;
  content: string;
}

export interface DocNavItem {
  slug: string;
  title: string;
}

export interface DocSection {
  title: string;
  items: DocNavItem[];
}

const docStructure: DocSection[] = [
  {
    title: "Getting Started",
    items: [
      { slug: "Introduction", title: "Introduction" },
      { slug: "How-It-Works", title: "How It Works" },
      { slug: "Usage", title: "Usage Guide" },
      { slug: "Features", title: "Features" },
    ],
  },
  {
    title: "Core Concepts",
    items: [
      { slug: "Architecture", title: "Architecture" },
      { slug: "Search", title: "How Search Works" },
      { slug: "Token-Economics", title: "Token Economics" },
    ],
  },
  {
    title: "Reference",
    items: [
      { slug: "API-Reference", title: "REST API" },
      { slug: "MCP-Server", title: "MCP Server" },
    ],
  },
  {
    title: "Guides",
    items: [
      { slug: "Deployment", title: "Deployment" },
      { slug: "CognitiveVault-Integration", title: "CognitiveVault Integration" },
    ],
  },
  {
    title: "Resources",
    items: [
      { slug: "Changelog", title: "Changelog" },
    ],
  },
];

export function getDocNavigation(): DocSection[] {
  return docStructure;
}

export function getAllDocSlugs(): string[] {
  const files = fs.readdirSync(docsDirectory);
  return files
    .filter((file) => file.endsWith(".md"))
    .map((file) => file.replace(/\.md$/, ""));
}

export function getDocBySlug(slug: string): DocPage | null {
  const fullPath = path.join(docsDirectory, `${slug}.md`);

  if (!fs.existsSync(fullPath)) {
    return null;
  }

  const fileContents = fs.readFileSync(fullPath, "utf8");
  const { data, content } = matter(fileContents);

  const titleMatch = content.match(/^#\s+(.+)$/m);
  const title =
    data.title || (titleMatch ? titleMatch[1] : slug.replace(/-/g, " "));

  return { slug, title, content };
}

export function extractTableOfContents(
  content: string
): { id: string; title: string; level: number }[] {
  const headingRegex = /^(#{2,4})\s+(.+)$/gm;
  const toc: { id: string; title: string; level: number }[] = [];
  let match;

  while ((match = headingRegex.exec(content)) !== null) {
    const level = match[1].length;
    const title = match[2];
    const id = title
      .toLowerCase()
      .replace(/[^\w\s-]/g, "")
      .replace(/\s+/g, "-");

    toc.push({ id, title, level });
  }

  return toc;
}
