import { Component } from "react";

/** Catches render/lifecycle errors anywhere below it so a single broken
 * component shows a readable panel instead of a blank white screen. React
 * error boundaries must be class components. The error is also sent to the
 * console (with the component stack) for DevTools inspection. */
export default class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { error: null, info: null };
  }

  static getDerivedStateFromError(error) {
    return { error };
  }

  componentDidCatch(error, info) {
    this.setState({ info });
    console.error("[sylqon] UI crashed:", error, info?.componentStack);
  }

  handleReload = () => {
    try {
      window.location.reload();
    } catch {
      this.setState({ error: null, info: null });
    }
  };

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="flex h-screen w-screen flex-col items-center justify-center gap-4 bg-bg-1 p-8 text-center">
        <div className="max-w-xl rounded-lg border border-bad/40 bg-bg-2/95 p-6 text-left">
          <h1 className="mb-2 font-display text-lg font-bold tracking-wide text-bad">
            Something went wrong
          </h1>
          <p className="mb-3 text-sm text-white/60">
            A component threw an unexpected error. The details are also in the
            developer console (DevTools).
          </p>
          <pre className="mb-4 max-h-48 overflow-auto rounded bg-black/40 p-3 text-2xs text-bad/90">
            {String(error?.stack || error?.message || error)}
            {info?.componentStack ? `\n${info.componentStack}` : ""}
          </pre>
          <button
            type="button"
            onClick={this.handleReload}
            className="rounded-md border border-accent/45 bg-accent/15 px-4 py-1.5 text-xs font-bold tracking-wide text-accent-bright transition-colors hover:bg-accent/25"
          >
            Reload
          </button>
        </div>
      </div>
    );
  }
}
