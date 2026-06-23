import React from "react";
import { createRoot } from "react-dom/client";
import "../node_modules/@douyinfe/semi-ui/dist/css/semi.min.css";
import "./styles.css";
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(
  <App />,
);
