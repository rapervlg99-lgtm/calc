/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_AUTH_DEV_TOKEN?: string
  readonly VITE_OCR_URL?: string
  /** Префикс приложения из vite `base` («/» или «/ozm/»), всегда со слешем на конце. */
  readonly BASE_URL: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
