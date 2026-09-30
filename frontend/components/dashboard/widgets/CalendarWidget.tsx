"use client";

import { CalendarDays, ChevronLeft, ChevronRight, Plus, Pencil, X, Check, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { apiFetch, formatApiError } from "@/lib/api";
import { parseEventDate } from "@/lib/eventTime";
import ModalPortal from "@/components/ModalPortal";
import { useDialog } from "@/context/dialog-context";

interface Holiday { id: number; name: string; date: string; is_mercantile: boolean }
interface Event   { id: number; title: string; event_date: string }
interface Props   { permissions: string[] }

const DAYS_OF_WEEK = ["Su", "Mo", "Tu", "We", "Th", "Fr", "Sa"];
const MONTH_NAMES  = ["January","February","March","April","May","June","July","August","September","October","November","December"];

export default function CalendarWidget({ permissions }: Props) {
  const canEdit = permissions.includes("widget.calendar.edit");
  const { showAlert, showConfirm } = useDialog();

  const now = new Date();
  const [year,  setYear]  = useState(now.getFullYear());
  const [month, setMonth] = useState(now.getMonth());

  const [holidays, setHolidays] = useState<Holiday[]>([]);
  const [events,   setEvents]   = useState<Event[]>([]);
  const [tooltip,  setTooltip]  = useState<{ day: number; labels: string[] } | null>(null);

  // Add Holiday modal
  const [modalOpen, setModalOpen] = useState(false);
  const [hName, setHName] = useState(""); const [hDate, setHDate] = useState(""); const [hMerc, setHMerc] = useState(true);
  const [saving, setSaving] = useState(false);

  // Edit holiday modal
  const [editHoliday, setEditHoliday] = useState<Holiday | null>(null);

  const load = async () => {
    try {
      // Only show events THIS user added to their calendar (via the "Add to
      // Calendar" button on the Upcoming Events widget), not every event in the
      // system. Holidays remain global.
      const [hr, er] = await Promise.all([apiFetch("/holidays"), apiFetch("/events/my-calendar")]);
      if (hr.ok) setHolidays(await hr.json());
      if (er.ok) setEvents(await er.json());
    } catch (e) { console.error(e); }
  };

  useEffect(() => {
    load();
    // Reload when an event is saved/removed elsewhere (Upcoming Events widget)
    // so the calendar reflects the change without a full page refresh.
    const onChange = () => load();
    window.addEventListener("calendar:changed", onChange);
    return () => window.removeEventListener("calendar:changed", onChange);
  }, []);
  useEffect(() => {
    const close = () => setTooltip(null);
    window.addEventListener("click", close);
    return () => window.removeEventListener("click", close);
  }, []);

  const prevMonth = () => { if (month === 0) { setMonth(11); setYear(y => y - 1); } else setMonth(m => m - 1); };
  const nextMonth = () => { if (month === 11) { setMonth(0); setYear(y => y + 1); } else setMonth(m => m + 1); };
  const goToday   = () => { setYear(now.getFullYear()); setMonth(now.getMonth()); };

  const firstDay    = new Date(year, month, 1).getDay();
  const daysInMonth = new Date(year, month + 1, 0).getDate();
  const cells: (number | null)[] = [...Array(firstDay).fill(null), ...Array.from({ length: daysInMonth }, (_, i) => i + 1)];

  const pad    = (n: number) => String(n).padStart(2, "0");
  const prefix = `${year}-${pad(month + 1)}`;

  const holidayMap = new Map<number, Holiday[]>();
  holidays.forEach((h) => {
    if (h.date.startsWith(prefix)) {
      const d = parseInt(h.date.split("-")[2]);
      holidayMap.set(d, [...(holidayMap.get(d) ?? []), h]);
    }
  });

  const eventMap = new Map<number, string[]>();
  events.forEach(ev => {
    const dt = parseEventDate(ev.event_date); // stored UTC → local calendar day
    if (dt.getFullYear() === year && dt.getMonth() === month) {
      const d = dt.getDate();
      eventMap.set(d, [...(eventMap.get(d) ?? []), ev.title]);
    }
  });

  const today       = now.getDate();
  const isThisMonth = now.getFullYear() === year && now.getMonth() === month;

  const openAddHoliday = () => { setHName(""); setHDate(`${year}-${pad(month + 1)}-01`); setHMerc(true); setEditHoliday(null); setModalOpen(true); };

  const handleSaveHoliday = async () => {
    setSaving(true);
    try {
      const body = JSON.stringify({ name: hName.trim(), date: hDate, is_mercantile: hMerc });
      const res = editHoliday
        ? await apiFetch(`/holidays/${editHoliday.id}`, { method: "PUT", body })
        : await apiFetch("/holidays", { method: "POST", body });
      if (!res.ok) {
        // Keep the modal open so the user can correct the input.
        const err = await res.json().catch(() => ({}));
        await showAlert(formatApiError(err.detail, "Unknown error"), {
          title: editHoliday ? "Failed to update holiday" : "Failed to save holiday",
        });
        return;
      }
      setModalOpen(false); setEditHoliday(null);
      load();
    } finally { setSaving(false); }
  };

  const handleDeleteHoliday = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
    const ok = await showConfirm("This holiday will be removed from the calendar.", {
      title: "Remove this holiday?",
      confirmText: "Remove",
    });
    if (!ok) return;
    await apiFetch(`/holidays/${id}`, { method: "DELETE" });
    load();
  };

  return (
    <>
      <div 
        onMouseLeave={() => setTooltip(null)}
        className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm h-full w-full flex flex-col"
      >
        {/* Header */}
        <div className="flex justify-between items-center mb-3">
          <div className="flex items-center gap-2">
            <button onClick={prevMonth} className="text-gray-400 hover:text-gray-600 transition"><ChevronLeft size={14} /></button>
            <button onClick={goToday} className="text-sm font-semibold text-gray-800 hover:text-[#F2924E] transition">
              {MONTH_NAMES[month]} {year}
            </button>
            <button onClick={nextMonth} className="text-gray-400 hover:text-gray-600 transition"><ChevronRight size={14} /></button>
          </div>
          <div className="flex items-center gap-2">
            {canEdit && (
              <button onClick={openAddHoliday} className="w-6 h-6 rounded-full bg-[#F2924E] text-white flex items-center justify-center hover:bg-orange-500 transition" title="Add holiday">
                <Plus size={12} />
              </button>
            )}
            <CalendarDays size={16} className="text-gray-400" />
          </div>
        </div>

        {/* Weekday headers */}
        <div className="grid grid-cols-7 mb-1">
          {DAYS_OF_WEEK.map((d) => (
            <div key={d} className="text-center text-[10px] font-medium text-gray-400 py-1">{d}</div>
          ))}
        </div>

        {/* Calendar grid */}
        <div className="grid grid-cols-7 gap-y-0.5 flex-1">
          {cells.map((day, i) => {
            const isToday   = isThisMonth && day === today;
            const isHoliday = day !== null && holidayMap.has(day);
            const hasEvent  = day !== null && eventMap.has(day);
            const holidays_ = day !== null ? (holidayMap.get(day) ?? []) : [];

            return (
              <div
                key={i}
                className="relative flex flex-col items-center justify-center"
                onClick={(e) => {
                  e.stopPropagation();
                  if (!day) return;
                  const labels = [...(holidayMap.get(day)?.map(h => `🏖 ${h.name}`) ?? []), ...(eventMap.get(day)?.map(e => `📅 ${e}`) ?? [])];
                  if (labels.length) {
                    if (tooltip?.day === day) setTooltip(null);
                    else setTooltip({ day, labels });
                  }
                }}
              >
                <div className={`
                  w-7 h-7 flex items-center justify-center rounded-full text-xs font-medium transition
                  ${isToday ? "bg-[#F2924E] text-white" : ""}
                  ${isHoliday && !isToday ? "bg-orange-100 text-orange-700" : ""}
                  ${hasEvent && !isHoliday && !isToday ? "bg-blue-50 text-blue-700" : ""}
                  ${!isToday && !isHoliday && !hasEvent && day ? "text-gray-700 hover:bg-gray-50" : ""}
                `}>
                  {day ?? ""}
                </div>

                {day !== null && (isHoliday || hasEvent) && (
                  <div className="flex gap-0.5 mt-0.5">
                    {isHoliday && <span className="w-1 h-1 rounded-full bg-orange-400" />}
                    {hasEvent   && <span className="w-1 h-1 rounded-full bg-blue-400" />}
                  </div>
                )}

                {/* Tooltip */}
                {tooltip?.day === day && (
                  <div className="absolute bottom-full left-1/2 -translate-x-1/2 pb-2 z-10 pointer-events-auto">
                    <div className="bg-gray-900 text-white text-[10px] px-3 py-2 rounded-xl shadow-lg min-w-[120px] max-w-[200px] space-y-2">
                      <div className="space-y-1">
                        {tooltip.labels.map((l, j) => <div key={j}>{l}</div>)}
                      </div>
                      
                      {canEdit && holidays_.length > 0 && (
                        <div className="pt-2 border-t border-white/20 flex flex-col gap-1.5">
                          {holidays_.map(h => (
                            <div key={h.id} className="flex items-center justify-between gap-3 bg-white/10 p-1.5 rounded-lg group/h">
                              <span className="truncate">{h.name}</span>
                              <div className="flex items-center gap-1 opacity-60 group-hover/h:opacity-100 transition">
                                <button 
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setHName(h.name); setHDate(h.date); setHMerc(h.is_mercantile);
                                    setEditHoliday(h); setModalOpen(true);
                                  }}
                                  className="p-1.5 hover:text-[#F2924E] transition rounded-md hover:bg-white/10"
                                  title="Edit holiday"
                                >
                                  <Pencil size={14} />
                                </button>
                                <button 
                                  onClick={(e) => handleDeleteHoliday(h.id, e)}
                                  className="p-1.5 hover:text-red-400 transition rounded-md hover:bg-white/10"
                                  title="Delete holiday"
                                >
                                  <Trash2 size={14} />
                                </button>
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                    <div className="w-2 h-2 bg-gray-900 rotate-45 mx-auto -mt-1" />
                  </div>
                )}
              </div>
            );
          })}
        </div>

        {/* Legend */}
        <div className="flex items-center gap-3 mt-2 pt-2 border-t border-gray-100">
          <div className="flex items-center gap-1 text-[10px] text-gray-400">
            <span className="w-2 h-2 rounded-full bg-orange-400 inline-block" /> Holiday
          </div>
          <div className="flex items-center gap-1 text-[10px] text-gray-400">
            <span className="w-2 h-2 rounded-full bg-blue-400 inline-block" /> Event
          </div>
          {canEdit && (
            <button
              onClick={openAddHoliday}
              className="text-[10px] text-[#F2924E] ml-auto hover:underline font-semibold transition"
            >
              + Add holiday
            </button>
          )}
        </div>
      </div>

      {/* Add/Edit Holiday Modal */}
      <ModalPortal open={modalOpen} onClose={() => setModalOpen(false)}>
          <div className="bg-white rounded-2xl shadow-2xl w-[420px] p-8">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold text-gray-900">{editHoliday ? "Edit Holiday" : "Add Holiday"}</h2>
              <button onClick={() => setModalOpen(false)} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Holiday Name</label>
                <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/40" value={hName} onChange={(e) => setHName(e.target.value)} maxLength={100} placeholder="e.g. Sinhala New Year" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Date</label>
                <input type="date" className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/40" value={hDate} min="2000-01-01" max="2100-12-31" onChange={(e) => setHDate(e.target.value)} />
              </div>
              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={hMerc} onChange={(e) => setHMerc(e.target.checked)} className="accent-[#F2924E]" />
                <span className="text-sm text-gray-700">Mercantile holiday</span>
              </label>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setModalOpen(false)} className="text-sm font-medium text-gray-600 px-4 py-2">Cancel</button>
              <button onClick={handleSaveHoliday} disabled={saving || !hName.trim() || !hDate} className="flex items-center gap-1.5 bg-[#F2924E] hover:bg-orange-500 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-lg transition">
                <Check size={14} /> {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
      </ModalPortal>
    </>
  );
}
