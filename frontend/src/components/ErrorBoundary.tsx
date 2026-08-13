import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "./Button";

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  componentDidCatch(_error: Error, _info: ErrorInfo) {
    // Production telemetry can subscribe here without exposing error details in the UI.
  }
  render() {
    if (this.state.failed) return <div className="page centered-state" role="alert"><h1>Bu ekran yüklenemedi</h1><p>Çalışmanızı kaybetmeden sayfayı yeniden deneyebilirsiniz.</p><Button onClick={() => { this.setState({ failed: false }); window.location.reload(); }}>Sayfayı yenile</Button></div>;
    return this.props.children;
  }
}
