import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import { bootstrapToken } from "./api/token";

// Capture the token from the pairing URL before anything renders, so the first request
// already carries it.
bootstrapToken();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
