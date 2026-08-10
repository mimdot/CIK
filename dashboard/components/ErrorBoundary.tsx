"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
  fallback?: ReactNode;
}

interface State {
  hasError: boolean;
  message?: string;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, message: error.message };
  }

  render() {
    if (this.state.hasError) {
      if (this.props.fallback) return this.props.fallback;
      return (
        <div
          role="alert"
          className="mx-auto my-10 max-w-md rounded-lg border border-destructive/30 bg-destructive/10 p-6 text-center text-sm text-destructive"
        >
          <h2 className="mb-1 text-base font-semibold">Something went wrong</h2>
          <p className="mb-4">
            {this.state.message ?? "An unexpected error occurred."}
          </p>
          <button
            onClick={() => this.setState({ hasError: false })}
            className="rounded-md border border-destructive/40 px-4 py-1.5 text-sm font-medium hover:bg-destructive/10"
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
