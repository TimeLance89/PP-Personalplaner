"use client";

import { FormEvent, useEffect, useMemo, useState } from "react";

type Task = {
  id: string;
  title: string;
  done: boolean;
  priority: "hoch" | "mittel" | "niedrig";
  due?: string;
};

const starterTasks: Task[] = [
  { id: "1", title: "Wochenplanung prüfen", done: false, priority: "hoch", due: "Heute" },
  { id: "2", title: "Offene Nachrichten beantworten", done: false, priority: "mittel", due: "Heute" },
  { id: "3", title: "Einkaufsliste aktualisieren", done: true, priority: "niedrig", due: "Erledigt" },
];

const appointments = [
  { time: "14:30", title: "Persönlicher Termin", detail: "30 Min." },
  { time: "18:00", title: "Freier Block", detail: "Zeit für Privates" },
];

function startOfWeek(date: Date) {
  const result = new Date(date);
  const day = result.getDay() || 7;
  result.setDate(result.getDate() - day + 1);
  result.setHours(0, 0, 0, 0);
  return result;
}

export default function Home() {
  const [tasks, setTasks] = useState<Task[]>(starterTasks);
  const [newTask, setNewTask] = useState("");
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const saved = window.localStorage.getItem("pp.tasks");
    if (saved) {
      try {
        setTasks(JSON.parse(saved));
      } catch {
        setTasks(starterTasks);
      }
    }
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (hydrated) window.localStorage.setItem("pp.tasks", JSON.stringify(tasks));
  }, [tasks, hydrated]);

  const today = useMemo(() => new Date(), []);
  const week = useMemo(() => {
    const monday = startOfWeek(today);
    return Array.from({ length: 7 }, (_, index) => {
      const date = new Date(monday);
      date.setDate(monday.getDate() + index);
      return date;
    });
  }, [today]);

  const openTasks = tasks.filter((task) => !task.done).length;
  const completedTasks = tasks.length - openTasks;
  const progress = tasks.length ? Math.round((completedTasks / tasks.length) * 100) : 0;

  function toggleTask(id: string) {
    setTasks((current) => current.map((task) => (task.id === id ? { ...task, done: !task.done } : task)));
  }

  function addTask(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const title = newTask.trim();
    if (!title) return;
    setTasks((current) => [
      { id: crypto.randomUUID(), title, done: false, priority: "mittel", due: "Neu" },
      ...current,
    ]);
    setNewTask("");
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">PP</div>
          <div>
            <strong>Personalplaner</strong>
            <span>Dein Alltag im Blick</span>
          </div>
        </div>

        <nav className="nav-list" aria-label="Hauptnavigation">
          <button className="nav-item active">◫ <span>Übersicht</span></button>
          <button className="nav-item">✓ <span>Aufgaben</span></button>
          <button className="nav-item">▦ <span>Kalender</span></button>
          <button className="nav-item">☰ <span>Wochenplan</span></button>
          <button className="nav-item">◎ <span>Routinen</span></button>
        </nav>

        <div className="sidebar-footer">
          <button className="nav-item">⚙ <span>Einstellungen</span></button>
          <div className="profile-mini">
            <div className="avatar">S</div>
            <div><strong>Mein Planer</strong><span>lokaler Modus</span></div>
          </div>
        </div>
      </aside>

      <section className="workspace">
        <header className="topbar">
          <div>
            <p className="eyebrow">{today.toLocaleDateString("de-DE", { weekday: "long", day: "2-digit", month: "long" })}</p>
            <h1>Guten Tag 👋</h1>
            <p>Hier ist dein persönlicher Überblick für heute.</p>
          </div>
          <button className="primary-button" onClick={() => document.getElementById("quick-task")?.focus()}>+ Neue Aufgabe</button>
        </header>

        <div className="stats-grid">
          <article className="stat-card"><span>Offene Aufgaben</span><strong>{openTasks}</strong><small>{completedTasks} bereits erledigt</small></article>
          <article className="stat-card"><span>Termine heute</span><strong>{appointments.length}</strong><small>Nächster um {appointments[0].time}</small></article>
          <article className="stat-card"><span>Tagesfortschritt</span><strong>{progress}%</strong><div className="progress"><i style={{ width: `${progress}%` }} /></div></article>
        </div>

        <div className="content-grid">
          <section className="panel tasks-panel">
            <div className="panel-head"><div><span className="panel-kicker">HEUTE</span><h2>Aufgaben</h2></div><button className="ghost-button">Alle anzeigen</button></div>
            <form className="quick-add" onSubmit={addTask}>
              <input id="quick-task" value={newTask} onChange={(event) => setNewTask(event.target.value)} placeholder="Was möchtest du erledigen?" />
              <button type="submit">Hinzufügen</button>
            </form>
            <div className="task-list">
              {tasks.map((task) => (
                <button key={task.id} className={`task-row ${task.done ? "done" : ""}`} onClick={() => toggleTask(task.id)}>
                  <span className="checkbox">{task.done ? "✓" : ""}</span>
                  <span className="task-copy"><strong>{task.title}</strong><small>{task.due}</small></span>
                  <span className={`priority ${task.priority}`}>{task.priority}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="panel agenda-panel">
            <div className="panel-head"><div><span className="panel-kicker">ZEITPLAN</span><h2>Heute</h2></div></div>
            <div className="agenda-list">
              {appointments.map((appointment) => (
                <div className="agenda-row" key={`${appointment.time}-${appointment.title}`}>
                  <time>{appointment.time}</time>
                  <div><strong>{appointment.title}</strong><span>{appointment.detail}</span></div>
                </div>
              ))}
            </div>
            <div className="focus-card"><span>Fokuszeit</span><strong>Plane bewusst freie Blöcke ein.</strong><small>PP soll später freie Kalenderfenster automatisch erkennen.</small></div>
          </section>
        </div>

        <section className="panel week-panel">
          <div className="panel-head"><div><span className="panel-kicker">DIESE WOCHE</span><h2>Wochenüberblick</h2></div><button className="ghost-button">Wochenplan öffnen</button></div>
          <div className="week-grid">
            {week.map((date) => {
              const isToday = date.toDateString() === today.toDateString();
              return (
                <div key={date.toISOString()} className={`day-card ${isToday ? "today" : ""}`}>
                  <span>{date.toLocaleDateString("de-DE", { weekday: "short" })}</span>
                  <strong>{date.getDate()}</strong>
                  <small>{isToday ? "Heute" : ""}</small>
                </div>
              );
            })}
          </div>
        </section>
      </section>
    </main>
  );
}
