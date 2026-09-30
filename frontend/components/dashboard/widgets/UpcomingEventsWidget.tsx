"use client";

import { useRouter } from "next/navigation";
import { CalendarDays, Plus, Pencil, Trash2, X, Check, CalendarPlus } from "lucide-react";
import { useEffect, useState } from "react";
import { apiFetch, formatApiError } from "@/lib/api";
import { parseEventDate, toDateTimeLocalInput, fromDateTimeLocalInput } from "@/lib/eventTime";
import ModalPortal from "@/components/ModalPortal";
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

interface Props { permissions: string[] }

export default function UpcomingEventsWidget({ permissions }: Props) {
  const router = useRouter();
  const canManage = permissions.includes("widget.upcoming_events.manage");
  const { showAlert, showConfirm } = useDialog();

  const [events, setEvents] = useState<Event[]>([]);
  const [loading, setLoading] = useState(true);
  const [modalOpen, setModalOpen] = useState(false);
  const [editItem, setEditItem] = useState<Event | null>(null);
  const [formTitle, setFormTitle] = useState("");
  const [formDesc, setFormDesc] = useState("");
  const [formDate, setFormDate] = useState("");
  const [formLocation, setFormLocation] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const res = await apiFetch("/events");
      // /events returns only FUTURE events (past auto-discarded by backend)
      if (res.ok) setEvents(await res.json());
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => { setEditItem(null); setFormTitle(""); setFormDesc(""); setFormDate(""); setFormLocation(""); setModalOpen(true); };
  const openEdit = (ev: Event, e: React.MouseEvent) => {
    e.stopPropagation();
    setEditItem(ev);
    setFormTitle(ev.title);
    setFormDesc(ev.description || "");
    setFormDate(toDateTimeLocalInput(ev.event_date));
    setFormLocation(ev.location || "");
    setModalOpen(true);
  };

  const handleDelete = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
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
      const endpoint = editItem ? `/events/${editItem.id}` : "/events";
      const method = editItem ? "PUT" : "POST";
      
      const res = await apiFetch(endpoint, {
        method,
        body: JSON.stringify(body)
      });
      
      if (res.ok) {
        setModalOpen(false);
        setEditItem(null);
        load();
      } else {
        const err = await res.json();
        await showAlert(formatApiError(err.detail, "Failed to save event"), { title: "Couldn't save event" });
      }
    } catch (e) {
      console.error(e);
      await showAlert("Could not connect to the server.", { title: "Network error" });
    } finally { setSaving(false); }
  };

  // "Add to Calendar" — saves/removes this event to the user's own dashboard
  // Calendar widget (per-user), then tells the Calendar widget to refresh.
  const toggleCalendar = async (ev: Event, e: React.MouseEvent) => {
    e.stopPropagation();
    try {
      const method = ev.is_saved ? "DELETE" : "POST";
      const res = await apiFetch(`/events/${ev.id}/save`, { method });
      if (res.ok) {
        setEvents(prev => prev.map(e => e.id === ev.id ? { ...e, is_saved: !ev.is_saved } : e));
        // Let the Calendar widget re-fetch the user's saved events immediately.
        window.dispatchEvent(new Event("calendar:changed"));
      }
    } catch (e) { console.error(e); }
  };

  // Stored UTC → shown in the viewer's local time (same as the Events page).
  const parseLocal = parseEventDate;

  const fmtDate = (d: string) =>
    parseLocal(d).toLocaleDateString("en-US", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

  const daysUntil = (d: string) => {
    const eventDate = parseLocal(d);
    const today = new Date();
    
    // Normalize to midnight for calendar day comparison
    const eDate = new Date(eventDate.getFullYear(), eventDate.getMonth(), eventDate.getDate());
    const tDate = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    
    const diffTime = eDate.getTime() - tDate.getTime();
    const diffDays = Math.round(diffTime / (1000 * 60 * 60 * 24));

    if (diffDays <= 0) return "Today";
    if (diffDays === 1) return "Tomorrow";
    return `In ${diffDays}d`;
  };

  return (
    <>
      <div
        className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm h-full w-full flex flex-col"
      >
        {/* Header */}
        <div className="flex justify-between items-center mb-5">
          <h3 className="text-base font-semibold text-gray-800">Upcoming Events</h3>
          <div className="flex items-center gap-2">
            {canManage && (
              <button
                onClick={(e) => { e.stopPropagation(); openCreate(); }}
                className="w-6 h-6 rounded-full bg-[#F2924E] text-white flex items-center justify-center hover:bg-orange-500 transition"
                title="New event"
              >
                <Plus size={12} />
              </button>
            )}
            <CalendarDays size={16} className="text-gray-400" />
          </div>
        </div>

        {/* Items */}
        <div className="space-y-4 flex-1">
          {loading ? (
            <p className="text-xs text-gray-400">Loading…</p>
          ) : events.length === 0 ? (
            <p className="text-xs text-gray-400">No upcoming events.</p>
          ) : (
            events.slice(0, 3).map((ev) => (
              <div key={ev.id} className="flex items-start gap-3">
                {/* Date badge */}
                <div className="flex-shrink-0 w-10 h-10 bg-orange-50 rounded-xl flex flex-col items-center justify-center">
                  <span className="text-[10px] font-bold text-[#F2924E] uppercase">
                    {parseLocal(ev.event_date).toLocaleDateString("en", { month: "short" })}
                  </span>
                  <span className="text-sm font-bold text-gray-900 leading-none">
                    {parseLocal(ev.event_date).getDate()}
                  </span>
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{ev.title}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{fmtDate(ev.event_date)}</p>
                  <span className="text-[10px] font-semibold text-[#F2924E] bg-orange-50 px-1.5 py-0.5 rounded-full mt-1 inline-block">
                    {daysUntil(ev.event_date)}
                  </span>
                </div>
                <div className="flex items-center gap-1 flex-shrink-0">
                  {/* Add to calendar button for all users */}
                  <button
                    onClick={(e) => toggleCalendar(ev, e)}
                    title={ev.is_saved ? "Remove from my Calendar" : "Add to my Dashboard Calendar"}
                    className={`p-1 transition ${ev.is_saved ? "text-[#F2924E]" : "text-gray-400 hover:text-[#F2924E]"}`}
                  >
                    <CalendarPlus size={13} className={ev.is_saved ? "fill-current" : ""} />
                  </button>
                  {canManage && (
                    <>
                      <button onClick={(e) => openEdit(ev, e)} className="p-1 text-gray-400 hover:text-blue-500 transition">
                        <Pencil size={12} />
                      </button>
                      <button onClick={(e) => handleDelete(ev.id, e)} className="p-1 text-gray-400 hover:text-red-500 transition">
                        <Trash2 size={12} />
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))
          )}
        </div>

        <div className="mt-auto pt-4 border-t border-gray-100 flex justify-end">
          <button 
            onClick={() => router.push("/dashboard/events")}
            className="text-[#f2924e] text-[10px] font-bold uppercase tracking-wider hover:underline"
          >
            View All
          </button>
        </div>
      </div>

      {/* Create/Edit Modal */}
      <ModalPortal open={modalOpen} onClose={() => setModalOpen(false)}>
          <div className="bg-white rounded-2xl shadow-2xl w-[480px] p-8">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold text-gray-900">{editItem ? "Edit Event" : "New Event"}</h2>
              <button onClick={() => setModalOpen(false)} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Title</label>
                <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/40" value={formTitle} onChange={(e) => setFormTitle(e.target.value)} maxLength={200} placeholder="Event title" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Date & Time</label>
                <input type="datetime-local" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/40" value={formDate} onChange={(e) => setFormDate(e.target.value)} />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Location (optional)</label>
                <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/40" value={formLocation} onChange={(e) => setFormLocation(e.target.value)} maxLength={200} placeholder="e.g. Conference Room A" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Description (optional)</label>
                <textarea className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/40 resize-none" rows={3} value={formDesc} onChange={(e) => setFormDesc(e.target.value)} maxLength={2000} placeholder="Event details…" />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setModalOpen(false)} className="text-sm font-medium text-gray-600 px-4 py-2">Cancel</button>
              <button onClick={handleSave} disabled={saving || !formTitle.trim() || !formDate} className="flex items-center gap-1.5 bg-[#F2924E] hover:bg-orange-500 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-lg transition">
                <Check size={14} /> {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
      </ModalPortal>
    </>
  );
}
