// Type information for the environment variables read through import.meta.env.
// Listing them here lets TypeScript catch typos such as VITE_API_BASE_UR.
interface ImportMetaEnv {
  readonly VITE_API_BASE_URL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
