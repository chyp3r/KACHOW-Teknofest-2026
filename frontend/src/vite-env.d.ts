/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_DEV_AUTH_BYPASS?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
