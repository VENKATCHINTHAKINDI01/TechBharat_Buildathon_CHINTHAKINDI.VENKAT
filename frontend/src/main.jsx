import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App.jsx";
import { LiveSessionProvider } from "./live/LiveSessionProvider.jsx";
import { ThemeProvider } from "./ui/theme.jsx";
import { ToastProvider } from "./ui/toast.jsx";
import "./styles.css";

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ThemeProvider>
      <ToastProvider>
        <LiveSessionProvider>
          <App />
        </LiveSessionProvider>
      </ToastProvider>
    </ThemeProvider>
  </React.StrictMode>
);
