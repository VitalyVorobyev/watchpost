import { useCallback, useEffect, useState } from "react";
import { useAppState } from "./api/useAppState";
import { setToken } from "./api/token";
import { Banner, Empty, Pill, connectionLabel } from "./components/ui";
import { EventDetail } from "./routes/EventDetail";
import { Events } from "./routes/Events";
import { Home } from "./routes/Home";
import { Host } from "./routes/Host";
import { Settings } from "./routes/Settings";
import "./styles/app.css";

/** Minimal path router. Five routes do not justify a routing dependency, and the client
 *  is served with an SPA fallback so deep links work. */
function usePath(): [string, (path: string) => void] {
  const [path, setPath] = useState(window.location.pathname);

  useEffect(() => {
    const onPop = () => setPath(window.location.pathname);
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, []);

  const navigate = useCallback((next: string) => {
    window.history.pushState({}, "", next);
    setPath(next);
    window.scrollTo(0, 0);
  }, []);

  return [path, navigate];
}

/** Loopback means we are on the Mac running the host, where "scan the QR code" is circular
 *  advice — this screen is the one that draws it. */
function isLoopback(): boolean {
  return ["127.0.0.1", "localhost", "::1", "[::1]"].includes(window.location.hostname);
}

function Pairing() {
  const [value, setValue] = useState("");
  const local = isLoopback();
  return (
    <div className="stack">
      <Empty
        title="Pair this device"
        body={
          local
            ? "Open the Mac link printed in the terminal when the host started — it carries the access token. You can also read it from the token file in the storage root and paste it below."
            : "Open Watchpost on the Mac and scan the QR code shown there. If you cannot scan it, paste the access token below."
        }
      />
      <input
        className="mono"
        style={{
          minHeight: "var(--tap)",
          padding: "0 var(--s3)",
          background: "var(--surface-raised)",
          color: "var(--text)",
          border: "1px solid var(--border-strong)",
          borderRadius: "var(--r2)",
        }}
        placeholder="Access token"
        value={value}
        onChange={(event) => setValue(event.target.value)}
      />
      <button
        className="btn btn--block"
        disabled={!value.trim()}
        onClick={() => {
          setToken(value.trim());
          window.location.reload();
        }}
      >
        Pair
      </button>
    </div>
  );
}

export function App() {
  const [path, navigate] = usePath();
  const { state, connection, eventTick, needsToken } = useAppState();

  const isHost = path.startsWith("/host");
  const link = connectionLabel(connection);

  let body: React.ReactNode;
  if (needsToken) {
    body = <Pairing />;
  } else if (isHost) {
    body = <Host state={state} connection={connection} />;
  } else if (path.startsWith("/events/")) {
    body = <EventDetail id={decodeURIComponent(path.slice("/events/".length))} navigate={navigate} />;
  } else if (path.startsWith("/events")) {
    body = <Events eventTick={eventTick} navigate={navigate} />;
  } else if (path.startsWith("/settings")) {
    body = <Settings />;
  } else {
    body = (
      <Home state={state} connection={connection} eventTick={eventTick} navigate={navigate} />
    );
  }

  const tabs = [
    { path: "/", label: "Home" },
    { path: "/events", label: "Events" },
    { path: "/settings", label: "Settings" },
  ];

  const current =
    path === "/" ? "/" : path.startsWith("/events") ? "/events" : path.startsWith("/settings") ? "/settings" : "/";

  return (
    <div className={`app ${isHost ? "app--host" : ""}`}>
      <header className="topbar">
        <a
          className="topbar__brand"
          href={isHost ? "/host" : "/"}
          onClick={(event) => {
            event.preventDefault();
            navigate(isHost ? "/host" : "/");
          }}
        >
          <img className="topbar__mark" src="/icon.svg" alt="" />
          Watchpost
        </a>
        <Pill tone={link.tone}>{link.text}</Pill>
      </header>

      <main className="app__main">
        <div className="stack">
          {!isHost && !needsToken && (
            <nav className="tabs" aria-label="Sections">
              {tabs.map((tab) => (
                <button
                  key={tab.path}
                  className="tabs__item"
                  aria-current={current === tab.path ? "page" : undefined}
                  onClick={() => navigate(tab.path)}
                >
                  {tab.label}
                </button>
              ))}
            </nav>
          )}

          {connection === "offline" && !needsToken && !isHost && (
            <Banner tone="danger" title="Offline">
              This device cannot reach the host right now.
            </Banner>
          )}

          {body}
        </div>
      </main>
    </div>
  );
}
