// @ts-check
import { defineConfig } from 'astro/config';
import starlight from '@astrojs/starlight';

export default defineConfig({
  site: 'https://edwinjosechittilappilly.github.io/harnessapi',
  base: '/harnessapi',
  output: 'static',
  integrations: [
    starlight({
      title: 'harnessapi',
      defaultLocale: 'root',
      locales: { root: { label: 'English', lang: 'en' } },
      description:
        'Python framework to build streaming APIs and MCP tools from skill folders. Write a skill. Get an API. Get an MCP tool. Ship.',
      social: [
        {
          icon: 'github',
          label: 'GitHub',
          href: 'https://github.com/edwinjosechittilappilly/harnessapi',
        },
        {
          icon: 'external',
          label: 'PyPI',
          href: 'https://pypi.org/project/harnessapi/',
        },
      ],
      editLink: {
        baseUrl:
          'https://github.com/edwinjosechittilappilly/harnessapi/edit/main/docs/',
      },
      customCss: ['./src/styles/custom.css'],
      expressiveCode: {
        themes: ['github-light', 'github-dark'],
        styleOverrides: {
          borderRadius: '10px',
          borderWidth: '1px',
          codeFontFamily: '"Geist Mono", "SF Mono", ui-monospace, monospace',
        },
      },
      components: {
        SiteTitle: './src/components/SiteTitle.astro',
        ThemeProvider: './src/components/ThemeProvider.astro',
      },
      sidebar: [
        {
          label: 'Get started',
          items: [
            { label: 'Introduction', slug: 'introduction' },
            { label: 'Quick start', slug: 'guides/quickstart' },
            { label: 'Installation', slug: 'guides/installation' },
          ],
        },
        {
          label: 'Core concepts',
          items: [
            { label: 'Skill folders', slug: 'concepts/skill-folders' },
            { label: 'Streaming (SSE)', slug: 'concepts/streaming' },
            { label: 'MCP tools', slug: 'concepts/mcp' },
          ],
        },
        {
          label: 'Examples',
          items: [
            { label: 'Factorial — streaming', slug: 'examples/factorial' },
            { label: 'Summarizer — LLM skill', slug: 'examples/summarizer' },
            { label: 'Web scraper', slug: 'examples/web-scraper' },
            { label: 'Image captioner', slug: 'examples/image-captioner' },
          ],
        },
        {
          label: 'Multi-tenancy',
          items: [
            { label: 'Overview', slug: 'multi-tenancy' },
            { label: 'Variant lifecycle', slug: 'multi-tenancy/variants' },
            { label: 'Preview & staging', slug: 'multi-tenancy/preview' },
            { label: 'Per-user sandboxes', slug: 'multi-tenancy/sandboxes' },
            { label: 'Storage backends', slug: 'multi-tenancy/storage' },
            { label: 'Admin MCP server', slug: 'multi-tenancy/admin-mcp' },
            { label: 'API reference', slug: 'multi-tenancy/api-reference' },
          ],
        },
        {
          label: 'Guides',
          items: [
            { label: 'Convert an agentskills.io skill', slug: 'guides/convert-skill' },
            { label: 'Connect to Claude Desktop', slug: 'guides/claude-desktop' },
            { label: 'Deploy to production', slug: 'guides/deploy' },
          ],
        },
        {
          label: 'CLI reference',
          items: [
            { label: 'harnessapi init', slug: 'reference/init' },
            { label: 'harnessapi run', slug: 'reference/run' },
          ],
        },
      ],
      head: [
        {
          tag: 'meta',
          attrs: {
            name: 'keywords',
            content:
              'harnessapi, MCP, Model Context Protocol, FastAPI, streaming API, SSE, Python, LLM tools, agent framework, skill framework, Claude, Cursor, FastMCP, agentskills',
          },
        },
        {
          tag: 'meta',
          attrs: { property: 'og:image', content: 'https://raw.githubusercontent.com/edwinjosechittilappilly/harnessapi/main/assets/banner.png' },
        },
        {
          tag: 'meta',
          attrs: { name: 'twitter:card', content: 'summary_large_image' },
        },
        {
          tag: 'meta',
          attrs: { name: 'twitter:image', content: 'https://raw.githubusercontent.com/edwinjosechittilappilly/harnessapi/main/assets/banner.png' },
        },
        {
          tag: 'link',
          attrs: {
            rel: 'alternate',
            type: 'text/plain',
            title: 'harnessapi — LLM-friendly docs index',
            href: 'https://edwinjosechittilappilly.github.io/harnessapi/llms.txt',
          },
        },
        { tag: 'link', attrs: { rel: 'preconnect', href: 'https://fonts.googleapis.com' } },
        { tag: 'link', attrs: { rel: 'preconnect', href: 'https://fonts.gstatic.com', crossorigin: '' } },
        {
          tag: 'link',
          attrs: {
            rel: 'stylesheet',
            href: 'https://fonts.googleapis.com/css2?family=Geist:wght@300;400;500;600;700&family=Geist+Mono:wght@400;500;600&family=Instrument+Serif:ital@0;1&display=swap',
          },
        },
      ],
    }),
  ],
});
