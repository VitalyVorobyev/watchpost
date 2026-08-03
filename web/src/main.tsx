import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { bootstrapToken } from "./api/token";

// Capture the token from the pairing URL before anything renders, so the first request
// already carries it.
const token = bootstrapToken();

// Point the manifest at a token-bearing URL so the host can answer with a matching
// `start_url`. iOS 16.4+ launches an installed app at `start_url`, and an installed app
// cannot see the token Safari stored — its storage container is separate — so the launch
// URL is the only channel that reaches it.
if (token) {
  const link = document.querySelector<HTMLLinkElement>('link[rel="manifest"]');
  if (link) link.href = `/manifest.webmanifest?t=${encodeURIComponent(token)}`;
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
