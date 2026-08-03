/// <reference types="vite/client" />

// TypeScript 7 requires a declaration for side-effect imports, including stylesheets.
declare module "*.css" {
  const content: string;
  export default content;
}
