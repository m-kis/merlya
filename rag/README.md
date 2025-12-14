# RAG (Cloudflare Worker)

This folder contains the documentation chatbot backend deployed as a Cloudflare Worker.

## Local development

```bash
cd rag
npm ci
npx wrangler dev
```

## Secrets (Cloudflare)

Secrets must **not** be committed to git.

Set the OpenAI key in the Worker environment:

```bash
cd rag
npx wrangler secret put OPENAI_API_KEY
```

## GitHub Actions deploy

The workflow `/.github/workflows/rag.yml` deploys the Worker on pushes to `main` (when `rag/**` changes),
but only if the repo secret `CLOUDFLARE_API_TOKEN` is configured.

