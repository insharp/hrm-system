"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ChevronRight, CalendarDays, Plus, Pencil, Trash2, X, Check, Search, CalendarPlus, MapPin, Clock } from "lucide-react";
import { apiFetch, formatApiError } from "@/lib/api";
import { parseEventDate, toDateTimeLocalInput, fromDateTimeLocalInput } from "@/lib/eventTime";
import { useAuth } from "@/context/auth-context";
import { useDialog } from "@/context/dialog-context";

interface Event {
  id: number;
  title: string;
  description?: string;
  event_date: string;
  location?: string;
  created_by: number;
  is_saved?: boolean;
}

type Filter = "upcoming" | "all";

export default function EventsPage() {
  const router = useRouter();
  const { user } = useAuth();
  const { showConfirm, showAlert } = useDialog();
  const canManage = user?.permissions?.includes("widget.upcoming_events.manage") ?? false;

  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<Filter>("upcoming");
  const [modalOpen, setModalOpen] = useState(false);
  const [editItem, setEditItem] = useState<Event | null>(null);
  const [formTitle, setFormTitle] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formDate, setFormDate] = useState("");
  const [formLocation, setFormLocation] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const endpoint = filter === "upcoming" ? "/events" : "/events/all";
      const res = await apiFetch(endpoint);
      if (res.ok) setEvents(await res.json());
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, [filter]);

  const filtered = events
    .filter((e) =>
      e.title.toLowerCase().includes(search.toLowerCase()) ||
      (e.location ?? "").toLowerCase().includes(search.toLowerCase())
    )
    .sort((a, b) => new Date(b.event_date).getTime() - new Date(a.event_date).getTime());

  const openCreate = () => { setEditItem(null); setFormTitle(""); setFormDesc(""); setFormDate(""); setFormLocation(""); setModalOpen(true); };
  const openEdit = (ev: Event) => { setEditItem(ev); setFormTitle(ev.title); setFormDesc(ev.description || ""); setFormDate(toDateTimeLocalInput(ev.event_date)); setFormLocation(ev.location || ""); setModalOpen(true); };
  const handleDelete = async (id: number) => {
    const ok = await showConfirm("This event will be permanently deleted.", {
      title: "Delete this event?",
      confirmText: "Delete",
    });
    if (!ok) return;
    await apiFetch(`/events/${id}`, { method: "DELETE" });
    load();
  };
  const handleSave = async () => {
    setSaving(true);
    try {
      const body = {
        title: formTitle.trim(),
        description: formDesc.trim() || null,
        event_date: fromDateTimeLocalInput(formDate),
        location: formLocation.trim() || null,
      };
      const res = editItem
        ? await apiFetch(`/events/${editItem.id}`, { method: "PUT", body: JSON.stringify(body) })
        : await apiFetch("/events", { method: "POST", body: JSON.stringify(body) });
      if (!res.ok) {
        // Previously the modal closed as if it had saved (e.g. a past date).
        const err = await res.json().catch(() => ({}));
        await showAlert(formatApiError(err.detail, "Failed to save event"), { title: "Couldn't save event" });
        return;
      }
      setModalOpen(false); load();
    } catch {
      await showAlert("Could not connect to the server.", { title: "Network error" });
    } finally { setSaving(false); }
  };

  const toggleCalendar = async (ev: Event) => {
    try {
      const method = ev.is_saved ? "DELETE" : "POST";
      const res = await apiFetch(`/events/${ev.id}/save`, { method });
      if (res.ok) {
        setEvents(prev => prev.map(e => e.id === ev.id ? { ...e, is_saved: !ev.is_saved } : e));
        window.dispatchEvent(new Event("calendar:changed"));
      }
    } catch (e) { console.error(e); }
  };

  const fmtDate = (d: string) => parseEventDate(d)
    .toLocaleDateString("en-US", { weekday: "short", year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

  const daysUntil = (d: string) => {
    const eventDate = parseEventDate(d);
    const today = new Date();
    
    const eDate = new Date(eventDate.getFullYear(), eventDate.getMonth(), eventDate.getDate());
    const tDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    
    const diffTime = eDate.getTime() - tDate.getTime();
    const diffDays = Math.round(diffTime / (1000 * 60 * 60 * 24));

    if (diffDays === 0) return "Today";
    if (diffDays === 1) return "Tomorrow";
    if (diffDays === -1) return "Yesterday";
    if (diffDays < -1) return `${Math.abs(diffDays)} days ago`;
    return `In ${diffDays} days`;
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-sm text-gray-500">
        <button onClick={() => router.push("/dashboard")} className="hover:text-[#F2924E] transition">Dashboard</button>
        <ChevronRight size={14} />
        <span className="text-gray-800 font-medium">Events</span>
      </nav>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 flex items-center gap-2">
            <CalendarDays size={22} className="text-[#F2924E]" /> Upcoming Events
          </h1>
          <p className="text-sm text-gray-500 mt-1">Company events, trainings, and important dates</p>
        </div>
        {canManage && (
          <button onClick={openCreate} className="flex items-center gap-2 bg-[#F2924E] hover:bg-orange-500 text-white text-sm font-medium px-5 py-2.5 rounded-xl transition shadow-sm">
            <Plus size={16} /> New Event
          </button>
        )}
      </div>

      {/* Toolbar */}
      <div className="flex items-center gap-3">
        <div className="relative flex-1 max-w-sm">
          <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
          <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search events…"
            className="w-full pl-9 pr-4 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#F2924E]/30" />
        </div>
        <div className="flex border border-gray-200 rounded-xl overflow-hidden">
          {(["upcoming", "all"] as Filter[]).map((f) => (
            <button key={f} onClick={() => setFilter(f)}
              className={`px-4 py-2.5 text-sm font-medium transition ${filter === f ? "bg-[#F2924E] text-white" : "text-gray-600 hover:bg-gray-50"}`}>
              {f === "upcoming" ? "Upcoming" : "All Events"}
            </button>
          ))}
        </div>
      </div>

      {/* Events list */}
      <div className="space-y-4">
        {loading ? (
          Array.from({ length: 3 }).map((_, i) => <div key={i} className="bg-white border border-gray-200 rounded-2xl p-6 animate-pulse h-28" />)
        ) : filtered.length === 0 ? (
          <div className="bg-white border border-gray-200 rounded-2xl p-12 text-center">
            <CalendarDays size={32} className="text-gray-200 mx-auto mb-3" />
            <p className="text-gray-500 font-medium">No events found</p>
            {canManage && <p className="text-sm text-gray-400 mt-1">Click &quot;New Event&quot; to create one</p>}
          </div>
        ) : (
          filtered.map((ev) => {
            const isPast = parseEventDate(ev.event_date) < new Date();
            return (
              <div key={ev.id} className={`bg-white border rounded-2xl p-6 hover:shadow-sm transition ${isPast ? "border-gray-100 opacity-70" : "border-gray-200"}`}>
                <div className="flex items-start gap-4">
                  {/* Date badge */}
                  <div className={`flex-shrink-0 w-14 h-14 rounded-2xl flex flex-col items-center justify-center ${isPast ? "bg-gray-100" : "bg-orange-50"}`}>
                    <span className={`text-[10px] font-bold uppercase ${isPast ? "text-gray-400" : "text-[#F2924E]"}`}>
                      {parseEventDate(ev.event_date).toLocaleDateString("en", { month: "short" })}
                    </span>
                    <span className={`text-xl font-bold leading-none ${isPast ? "text-gray-500" : "text-gray-900"}`}>
                      {parseEventDate(ev.event_date).getDate()}
                    </span>
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-start justify-between gap-2">
                      <h3 className="text-base font-semibold text-gray-900">{ev.title}</h3>
                      <span className={`text-xs font-semibold px-2.5 py-0.5 rounded-full flex-shrink-0 ${
                        isPast ? "bg-gray-100 text-gray-500" : "bg-orange-50 text-[#F2924E]"
                      }`}>
                        {daysUntil(ev.event_date)}
                      </span>
                    </div>
                    {ev.description && <p className="text-sm text-gray-600 mt-1">{ev.description}</p>}
                    <div className="flex items-center gap-4 mt-2">
                      <span className="flex items-center gap-1 text-xs text-gray-400">
                        <Clock size={12} /> {fmtDate(ev.event_date)}
                      </span>
                      {ev.location && (
                        <span className="flex items-center gap-1 text-xs text-gray-400">
                          <MapPin size={12} /> {ev.location}
                        </span>
                      )}
                    </div>
                  </div>

                  {/* Actions */}
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button 
                      onClick={() => toggleCalendar(ev)} 
                      title={ev.is_saved ? "Remove from my Calendar" : "Add to my Dashboard Calendar"}
                      className={`p-2 border rounded-lg transition ${
                        ev.is_saved 
                          ? "bg-orange-50 border-orange-200 text-[#F2924E]" 
                          : "text-gray-400 hover:text-[#F2924E] border-gray-200"
                      }`}
                    >
                      <CalendarPlus size={14} className={ev.is_saved ? "fill-current" : ""} />
                    </button>
                    {canManage && !isPast && (
                      <>
                        <button onClick={() => openEdit(ev)} className="p-2 text-gray-400 hover:text-blue-500 border border-gray-200 rounded-lg transition">
                          <Pencil size={14} />
                        </button>
                        <button onClick={() => handleDelete(ev.id)} className="p-2 text-gray-400 hover:text-red-500 border border-gray-200 rounded-lg transition">
                          <Trash2 size={14} />
                        </button>
                      </>
                    )}
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setModalOpen(false)}>
          <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" />
          <div className="relative bg-white rounded-2xl shadow-2xl w-[560px] p-8 z-10" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold text-gray-900">{editItem ? "Edit Event" : "New Event"}</h2>
              <button onClick={() => setModalOpen(false)} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Title</label>
                <input className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/30" value={formTitle} onChange={(e) => setFormTitle(e.target.value)} maxLength={200} placeholder="Event title" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Date & Time</label>
                <input type="datetime-local" className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/30" value={formDate} onChange={(e) => setFormDate(e.target.value)} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Location (optional)</label>
                <input className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/30" value={formLocation} onChange={(e) => setFormLocation(e.target.value)} maxLength={200} placeholder="e.g. Main Conference Hall" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description (optional)</label>
                <textarea className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/30 resize-none" rows={4} value={formDesc} onChange={(e) => setFormDesc(e.target.value)} maxLength={2000} placeholder="Event details…" />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setModalOpen(false)} className="text-sm font-medium text-gray-600 px-4 py-2">Cancel</button>
              <button onClick={handleSave} disabled={saving || !formTitle.trim() || !formDate}
                className="flex items-center gap-1.5 bg-[#F2924E] hover:bg-orange-500 disabled:opacity-50 text-white text-sm font-medium px-6 py-2.5 rounded-xl transition">
                <Check size={14} /> {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}