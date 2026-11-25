import React from "react";
import ReactDOM from "react-dom/client";
import "../../css/fonts.css";
import "../../css/design-tokens.css";
import "../../css/direction-switch.css";
import App from "./App";
import "./index.css";
import "./admin.css";
import "./fonts.css";
import "./public-sparta.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
