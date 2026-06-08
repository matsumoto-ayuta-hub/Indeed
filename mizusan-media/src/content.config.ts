import { defineCollection, z } from "astro:content";
import { glob } from "astro/loaders";

const articles = defineCollection({
  loader: glob({ pattern: "**/*.{md,mdx}", base: "./src/content/articles" }),
  schema: z.object({
    title: z.string().min(10).max(40),
    description: z.string().max(160),
    cluster: z.enum(["suisankako", "yoshoku", "ryoshi", "eigyo"]),
    intent: z.enum(["know", "do", "buy"]),
    targetKeyword: z.string(),
    pubDate: z.coerce.date(),
    updatedDate: z.coerce.date().optional(),
    author: z.string(),
    supervisor: z.string().optional(),
    heroImage: z.string().optional(),
    isPillar: z.boolean().default(false),
    related: z.array(z.string()).default([]),
    faq: z
      .array(
        z.object({
          q: z.string(),
          a: z.string(),
        })
      )
      .default([]),
    draft: z.boolean().default(true),
  }),
});

const authors = defineCollection({
  loader: glob({ pattern: "**/*.{md,mdx}", base: "./src/content/authors" }),
  schema: z.object({
    name: z.string(),
    role: z.string(),
    bio: z.string(),
    credentials: z.string().optional(),
  }),
});

export const collections = { articles, authors };
