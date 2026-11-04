"use client";
import "@/App.css";
import BeatHouseRoutePlanner from "./Component/Map/BeatHouseRoutePlanner";
import AnalyticsDashboard from "./Component/AnalyticsDashboard";
import {useState} from "react";

export default function App() {
    const [activePlanner, setActivePlanner] = useState("route");

    return (
        <div className="flex h-screen min-h-0 flex-col">
            <nav className="flex shrink-0 flex-nowrap gap-2 overflow-x-auto border-b bg-white px-4 py-2">
                <button
                    type="button"
                    onClick={() => setActivePlanner("route")}
                    className={`shrink-0 rounded px-4 py-2 text-sm font-medium ${activePlanner === "route" ? "bg-blue-700 text-white" : "text-slate-700 hover:bg-slate-100"}`}
                >
                    Route Optimization
                </button>
                <button
                    type="button"
                    onClick={() => setActivePlanner("analytics")}
                    className={`shrink-0 rounded px-4 py-2 text-sm font-medium ${activePlanner === "analytics" ? "bg-blue-700 text-white" : "text-slate-700 hover:bg-slate-100"}`}
                >
                    Employee Performance Analysis
                </button>
            </nav>
            <main className="min-h-0 flex-1">
                <div className={`h-full ${activePlanner === "route" ? "" : "hidden"}`}>
                    <BeatHouseRoutePlanner visible={activePlanner === "route"}/>
                </div>
                <div className={`h-full ${activePlanner === "analytics" ? "" : "hidden"}`}>
                    <AnalyticsDashboard visible={activePlanner === "analytics"}/>
                </div>
            </main>
        </div>
    );
}
