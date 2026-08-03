/** Last line of defence against a blank page.
 *
 * React unmounts the whole tree when a render throws, so a single bad field access shows
 * the user nothing at all and puts the real cause somewhere only a developer console will
 * find it. That happened for real: a client rebuilt against a newer host read a state field
 * an older running host did not send. `adoptState` handles that specific case; this handles
 * the ones not thought of yet.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";

export class ErrorBoundary extends Component<{ children: ReactNode }, { message: string | null }> {
  state = { message: null as string | null };

  static getDerivedStateFromError(error: unknown): { message: string } {
    return { message: error instanceof Error ? error.message : String(error) };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    console.error("Watchpost failed to render", error, info.componentStack);
  }

  render(): ReactNode {
    if (this.state.message === null) return this.props.children;
    return (
      <div className="stack" style={{ padding: "var(--s5)" }}>
        <div className="banner banner--danger">
          <strong className="banner__title">Watchpost could not display this page</strong>
          <p style={{ margin: 0 }}>
            This usually means the host is running an older version than the page it served.
            Restarting the host resolves it.
          </p>
          <p className="mono" style={{ marginBottom: 0, opacity: 0.75 }}>
            {this.state.message}
          </p>
        </div>
        <button className="btn btn--block" onClick={() => window.location.reload()}>
          Reload
        </button>
      </div>
    );
  }
}
