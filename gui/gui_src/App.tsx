import "./App.css";

import { BrowserRouter, Routes, Route } from "react-router-dom";

import Layout from "./components/layout/Layout";

import Dashboard from "./pages/dashboard/Dashboard";
import Chat from "./pages/Chat/AiChat";
import CrystalExplorer from "./pages/crystals/CrystalExplorer";
import Papers from "./pages/papers/Papers";
import Database from "./pages/database/Database";
import Settings from "./pages/settings/Settings";
import CrystalDetails from "./pages/details/CrystalDetails";

function App() {
  return (

    /* Enable React Router */
    <BrowserRouter>

      {/* Route Container */}
      <Routes>

        {/* Main Layout */}
        <Route path="/" element={<Layout />}>

          {/* Dashboard */}
          <Route index element={<Dashboard />} />

          {/* Chat */}
          <Route path="chat" element={<Chat />} />

          {/* Crystal Explorer */}
          <Route path="crystals" element={<CrystalExplorer />} />

          {/* Crystal Details */}
          <Route
            path="crystal/:id"
            element={<CrystalDetails />}
          />

          {/* Papers */}
          <Route path="papers" element={<Papers />} />

          {/* Database */}
          <Route path="database" element={<Database />} />

          {/* Settings */}
          <Route path="settings" element={<Settings />} />

        </Route>

      </Routes>

    </BrowserRouter>

  );
}

export default App;