import { Component, type ErrorInfo, type ReactNode } from 'react';
import { createRoot } from 'react-dom/client';
import App from './App';
import './styles.css';

class WorkspaceBoundary extends Component<{ children: ReactNode }, { error: boolean }> {
  state = { error: false };
  static getDerivedStateFromError() { return { error: true }; }
  componentDidCatch(_error: Error, _info: ErrorInfo) { /* Do not log dataset contents or the session token. */ }
  render() {
    if (this.state.error) return <main className="fatal-error"><h1>The workspace could not render.</h1><p>Reload to reconnect to the local API. Source data and jobs remain on the server.</p><button onClick={() => window.location.reload()}>Reload workspace</button></main>;
    return this.props.children;
  }
}
createRoot(document.getElementById('root')!).render(<WorkspaceBoundary><App /></WorkspaceBoundary>);
