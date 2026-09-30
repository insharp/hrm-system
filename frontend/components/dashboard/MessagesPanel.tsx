"use client";

import { useState, useEffect, useRef } from "react";
import { X, Search, MoreVertical, ArrowLeft, Send, Trash2, CheckSquare, Square, RotateCcw, CheckCircle2, Inbox, Mail } from "lucide-react";
import { formatDistanceToNow } from "date-fns";
import { apiFetch, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/auth-context";
import { useDialog } from "@/context/dialog-context";

const PREVIEW_LEN = 70;

export interface Message {
  id: number;
  sender_id: number;
  sender_name: string;
  subject: string;
  content: string;
  target_group: string;
  is_read: boolean;
  is_deleted: boolean;
  sender_deleted: boolean;
  created_at: string;
}

interface Props { isOpen: boolean; onClose: () => void; }
type Tab  = "inbox" | "sent" | "trash";
type View = "list" | "read" | "compose" | "sent_success";

export default function MessagesPanel({ isOpen, onClose }: Props) {
  const { hasPermission, user: authUser } = useAuth();
  const { showAlert, showConfirm } = useDialog();
  const canSend = hasPermission("messaging.send");
  // Use the actual DB flag \u2014 not a role name string match which is fragile
  const isSuperAdmin = authUser?.is_superadmin === true;

  const [view,        setView]        = useState<View>("list");
  const [tab,         setTab]         = useState<Tab>("inbox");
  const [messages,    setMessages]    = useState<Message[]>([]);
  const [selected,    setSelected]    = useState<Message | null>(null);
  const [search,      setSearch]      = useState("");
  const [checkedIds,  setCheckedIds]  = useState<Set<number>>(new Set());
  const [menuId,      setMenuId]      = useState<number | null>(null);

  // Compose state
  const [subject,      setSubject]      = useState("");
  const [targetGroup,  setTargetGroup]  = useState("All Employees");
  const [body,         setBody]         = useState("");
  const [sending,      setSending]      = useState(false);
  const [sentSubject,  setSentSubject]  = useState("");
  const [sentTarget,   setSentTarget]   = useState("");
  const [departments,  setDepartments]  = useState<string[]>([]);
  const [customGroups, setCustomGroups] = useState<{id: number; name: string}[]>([]);
  const [newGroupName, setNewGroupName] = useState("");
  const [addingGroup,  setAddingGroup]  = useState(false);
  const [showGroupInput, setShowGroupInput] = useState(false);



  // ── Fetch ──────────────────────────────────────────────────────────────────
  const fetchMessages = async () => {
    try {
      const res = await apiFetch(`/messages/${tab}`);
      if (res.ok) setMessages(await res.json());
    } catch {}
  };

  const fetchComposeData = async () => {
    try {
      const [dRes, gRes] = await Promise.all([
        apiFetch("/departments/"),
        apiFetch("/messages/groups"),
      ]);
      if (dRes.ok) {
        const data = await dRes.json();
        setDepartments(data.map((d: any) => d.name).filter(Boolean));
      }
      if (gRes.ok) setCustomGroups(await gRes.json());
    } catch {}
  };

  useEffect(() => {
    if (isOpen) {
      fetchMessages();
      setView("list");
      setSelected(null);
      setCheckedIds(new Set());
      if (canSend) fetchComposeData();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, tab]);

  // Close menu on outside click
  const panelRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuId !== null && panelRef.current && !panelRef.current.contains(e.target as Node)) {
        setMenuId(null);
      }
    };
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, [menuId]);

  // ── Actions ────────────────────────────────────────────────────────────────
  const handleSend = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!subject.trim() || !body.trim()) return;
    setSending(true);
    try {
      const res = await apiFetch("/messages/", {
        method: "POST",
        body: JSON.stringify({ target_group: targetGroup, subject: subject.trim(), content: body.trim() }),
      });
      if (res.ok) {
        setSentSubject(subject); setSentTarget(targetGroup);
        setSubject(""); setBody(""); setTargetGroup("All Employees");
        setView("sent_success");
        setTab("sent");
      } else {
        // e.g. the chosen group has nobody in it — tell the sender instead of
        // leaving them on the compose form wondering what happened.
        const err = await res.json().catch(() => ({}));
        await showAlert(formatApiError(err.detail, "Failed to send message"), { title: "Message not sent" });
      }
    } catch {
      await showAlert("Could not connect to the server.", { title: "Network error" });
    }
    finally { setSending(false); }
  };

  const softDelete = async (id: number) => {
    await apiFetch(`/messages/${id}/delete`, { method: "PUT" });
    await fetchMessages();
    setMenuId(null);
    if (selected?.id === id) setView("list");
  };

  const restore = async (id: number) => {
    await apiFetch(`/messages/${id}/restore`, { method: "PUT" });
    await fetchMessages();
    setMenuId(null);
  };

  const permDelete = async (id: number) => {
    await apiFetch(`/messages/${id}/permanent`, { method: "DELETE" });
    await fetchMessages();
    setMenuId(null);
  };

  const markRead = async (msg: Message) => {
    if (!msg.is_read && tab === "inbox") {
      await apiFetch(`/messages/${msg.id}/read`, { method: "PUT" });
      setMessages(prev => prev.map(m => m.id === msg.id ? { ...m, is_read: true } : m));
    }
    setSelected(msg);
    setView("read");
  };

  const bulkAction = async (action: "delete" | "restore" | "permDelete") => {
    for (const id of Array.from(checkedIds)) {
      if (action === "delete")     await apiFetch(`/messages/${id}/delete`,    { method: "PUT" });
      if (action === "restore")    await apiFetch(`/messages/${id}/restore`,   { method: "PUT" });
      if (action === "permDelete") await apiFetch(`/messages/${id}/permanent`, { method: "DELETE" });
    }
    setCheckedIds(new Set());
    fetchMessages();
  };

  const toggle = (id: number) => setCheckedIds(prev => {
    const next = new Set(prev);
    next.has(id) ? next.delete(id) : next.add(id);
    return next;
  });

  // ── Derived ────────────────────────────────────────────────────────────────
  const visible = messages.filter(m => {
    if (!search) return true;
    const q = search.toLowerCase();
    return m.subject?.toLowerCase().includes(q) || m.sender_name.toLowerCase().includes(q) || m.content.toLowerCase().includes(q);
  });

  const initials = (name: string) =>
    name.split(" ").map(n => n[0]).join("").slice(0, 2).toUpperCase() || "?";

  const senderLabel = (msg: Message) => {
    if (tab !== "sent") return msg.sender_name;
    const map: Record<string, string> = { "All Employees": "All Employees", "All": "Everyone", "HR": "HR Dept" };
    return `→ ${map[msg.target_group] || msg.target_group}`;
  };

  const avatarInitials = (msg: Message) => {
    if (tab !== "sent") return initials(msg.sender_name);
    const tg = msg.target_group;
    if (tg === "All" || tg === "All Employees") return "ALL";
    return tg.slice(0, 2).toUpperCase();
  };

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <>
      {/* Backdrop */}
      <div
        className={`fixed inset-0 bg-black/30 z-40 transition-opacity duration-300 ${isOpen ? "opacity-100 pointer-events-auto" : "opacity-0 pointer-events-none"}`}
        onClick={onClose}
      />

      {/* Drawer */}
      <div
        ref={panelRef}
        className={`fixed top-0 right-0 h-screen w-[460px] max-w-[95vw] bg-white shadow-2xl z-50 flex flex-col
          transition-transform duration-300 ease-in-out
          ${isOpen ? "translate-x-0" : "translate-x-full"}`}
      >
        {/* ── Header ── */}
        <div className="bg-[#f08a4b] text-white flex-shrink-0">
          <div className="flex items-center justify-between px-5 py-4">
            <div className="flex items-center gap-2">
              {(view === "read" || view === "compose") && (
                <button onClick={() => setView("list")} className="p-1.5 hover:bg-white/20 rounded-full transition -ml-1">
                  <ArrowLeft size={16} />
                </button>
              )}
              <Mail size={18} className="opacity-80" />
              <h2 className="text-base font-bold tracking-wide">
                {view === "list" && "Messages"}
                {view === "read" && "Read Message"}
                {view === "compose" && "New Message"}
                {view === "sent_success" && "Message Sent"}
              </h2>
            </div>
            <button onClick={onClose} className="p-1.5 hover:bg-white/20 rounded-full transition">
              <X size={18} />
            </button>
          </div>

          {/* Search + Tabs — only in list view */}
          {(view === "list" || view === "sent_success") && (
            <div className="px-5 pb-3 space-y-3">
              <div className="relative">
                <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-orange-200" />
                <input
                  type="text"
                  placeholder="Search messages…"
                  value={search}
                  onChange={e => setSearch(e.target.value)}
                  className="w-full bg-white/20 placeholder-orange-100 text-white text-sm rounded-lg pl-9 pr-4 py-2 focus:outline-none focus:bg-white/30 transition"
                />
              </div>
              <div className="flex gap-5">
                {(["inbox", ...(canSend ? ["sent"] : []), "trash"] as Tab[]).map(t => (
                  <button
                    key={t}
                    onClick={() => { setTab(t); setCheckedIds(new Set()); setView("list"); }}
                    className={`pb-1.5 text-sm font-semibold border-b-2 transition capitalize ${tab === t ? "border-white text-white" : "border-transparent text-white/60 hover:text-white"}`}
                  >
                    {t}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>

        {/* ── Sent Success ── */}
        {view === "sent_success" && (
          <div className="flex-1 flex flex-col items-center justify-center gap-5 p-8 text-center bg-gray-50">
            <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center">
              <CheckCircle2 size={32} className="text-green-500" />
            </div>
            <div>
              <h3 className="text-lg font-bold text-gray-900 mb-1">Message Sent!</h3>
              <p className="text-sm text-gray-500 leading-relaxed">
                <span className="font-semibold text-gray-700">"{sentSubject}"</span> sent to{" "}
                <span className="font-semibold text-[#f08a4b]">{sentTarget}</span>.
              </p>
            </div>
            <div className="flex flex-col gap-2 w-full">
              <button
                onClick={() => { setSubject(""); setBody(""); setTargetGroup("All Employees"); setView("compose"); }}
                className="bg-[#f08a4b] hover:bg-[#e47d3d] text-white py-2.5 rounded-xl text-sm font-bold flex items-center justify-center gap-2 transition"
              >
                <Send size={14} /> Send Another
              </button>
              <button
                onClick={() => setView("list")}
                className="border border-gray-200 text-gray-700 py-2.5 rounded-xl text-sm font-semibold hover:bg-gray-50 transition"
              >
                Back to {tab === "sent" ? "Sent" : "Inbox"}
              </button>
            </div>
          </div>
        )}

        {/* ── List View ── */}
        {view === "list" && (
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Toolbar */}
            <div className="px-4 py-2.5 border-b border-gray-100 bg-white flex items-center justify-between flex-shrink-0">
              {checkedIds.size > 0 ? (
                <>
                  <div className="flex items-center gap-2">
                    <button onClick={() => setCheckedIds(new Set())} className="text-[#f08a4b]"><CheckSquare size={16} /></button>
                    <span className="text-sm font-semibold text-[#f08a4b]">{checkedIds.size} selected</span>
                  </div>
                  <div className="flex gap-2">
                    {tab === "trash" && (
                      <button onClick={() => bulkAction("restore")} className="px-3 py-1 bg-green-100 text-green-700 rounded-lg text-xs font-bold flex items-center gap-1">
                        <RotateCcw size={12} /> Restore
                      </button>
                    )}
                    <button
                      onClick={() => bulkAction(tab === "trash" ? "permDelete" : "delete")}
                      className="px-3 py-1 bg-red-100 text-red-600 rounded-lg text-xs font-bold flex items-center gap-1"
                    >
                      <Trash2 size={12} /> {tab === "trash" ? "Delete Forever" : "Trash"}
                    </button>
                  </div>
                </>
              ) : (
                <>
                  <button
                    onClick={() => setCheckedIds(new Set(visible.map(m => m.id)))}
                    className="flex items-center gap-2 text-gray-400 hover:text-gray-600 text-xs font-semibold"
                  >
                    <Square size={15} /> Select All
                  </button>
                  {canSend && (
                    <button
                      onClick={() => { setSubject(""); setBody(""); setTargetGroup("All Employees"); setView("compose"); }}
                      className="text-[#f08a4b] text-xs font-bold hover:underline flex items-center gap-1"
                    >
                      <Send size={12} /> New Message
                    </button>
                  )}
                </>
              )}
            </div>

            {/* Message list */}
            <div className="flex-1 overflow-y-auto">
              {visible.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-full gap-3 text-gray-400">
                  <Inbox size={36} className="opacity-30" />
                  <p className="text-sm">{tab === "inbox" ? "Your inbox is empty" : `No messages in ${tab}`}</p>
                </div>
              ) : (
                visible.map(msg => {
                  const isChecked = checkedIds.has(msg.id);
                  const isUnread  = !msg.is_read && tab === "inbox";
                  return (
                    <div
                      key={msg.id}
                      className={`relative flex items-start gap-3 px-4 py-3.5 border-b border-gray-100 group transition-colors
                        ${isChecked ? "bg-orange-50" : isUnread ? "bg-blue-50/40 hover:bg-blue-50/60" : "hover:bg-gray-50"}`}
                    >
                      {isUnread && <div className="absolute left-0 top-0 h-full w-0.5 bg-[#f08a4b]" />}

                      {/* Checkbox */}
                      <button onClick={() => toggle(msg.id)} className="mt-1 shrink-0 text-gray-300 hover:text-[#f08a4b] transition">
                        {isChecked ? <CheckSquare size={16} className="text-[#f08a4b]" /> : <Square size={16} />}
                      </button>

                      {/* Avatar */}
                      <div
                        onClick={() => markRead(msg)}
                        className={`h-9 w-9 shrink-0 rounded-full flex items-center justify-center font-bold text-xs cursor-pointer
                          ${tab === "sent" ? "bg-orange-100 text-[#f08a4b]" : "bg-gray-100 text-gray-600"}`}
                      >
                        {avatarInitials(msg)}
                      </div>

                      {/* Content */}
                      <div className="flex-1 min-w-0 cursor-pointer" onClick={() => markRead(msg)}>
                        <div className="flex items-start justify-between gap-2 mb-0.5">
                          <p className={`text-sm truncate ${isUnread ? "font-bold text-gray-900" : "font-semibold text-gray-700"}`}>
                            {senderLabel(msg)}
                          </p>
                          <span className="text-[10px] text-gray-400 shrink-0 mt-0.5">
                            {formatDistanceToNow(new Date(msg.created_at), { addSuffix: true })}
                          </span>
                        </div>
                        <p className={`text-xs truncate ${isUnread ? "font-semibold text-gray-700" : "text-gray-500"}`}>{msg.subject}</p>
                        <p className="text-[11px] text-gray-400 truncate mt-0.5">{msg.content.slice(0, PREVIEW_LEN)}…</p>
                      </div>

                      {/* Row menu */}
                      <div className="shrink-0 relative self-start mt-1">
                        <button
                          onClick={e => { e.stopPropagation(); setMenuId(menuId === msg.id ? null : msg.id); }}
                          className="p-1 rounded-full text-gray-300 hover:text-gray-600 hover:bg-gray-100 opacity-0 group-hover:opacity-100 transition"
                        >
                          <MoreVertical size={15} />
                        </button>
                        {menuId === msg.id && (
                          <div className="absolute right-0 top-full mt-1 bg-white border border-gray-100 shadow-xl rounded-xl py-1 w-40 z-20">
                            {tab === "trash" ? (
                              <>
                                <button onClick={() => restore(msg.id)} className="w-full text-left px-4 py-2 text-sm text-gray-700 hover:bg-gray-50 flex items-center gap-2">
                                  <RotateCcw size={13} /> Restore
                                </button>
                                <button onClick={() => permDelete(msg.id)} className="w-full text-left px-4 py-2 text-sm text-red-500 hover:bg-red-50 flex items-center gap-2 border-t border-gray-100">
                                  <Trash2 size={13} /> Delete Forever
                                </button>
                              </>
                            ) : (
                              <button onClick={() => softDelete(msg.id)} className="w-full text-left px-4 py-2 text-sm text-red-500 hover:bg-red-50 flex items-center gap-2">
                                <Trash2 size={13} /> Move to Trash
                              </button>
                            )}
                          </div>
                        )}
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </div>
        )}

        {/* ── Read View ── */}
        {view === "read" && selected && (
          <div className="flex-1 flex flex-col bg-gray-50 overflow-hidden">
            <div className="bg-white px-5 py-3.5 border-b border-gray-100 flex items-center justify-between flex-shrink-0">
              <div className="flex items-center gap-3">
                <div className="h-9 w-9 shrink-0 bg-gray-100 text-gray-600 rounded-full flex items-center justify-center font-bold text-xs">
                  {initials(selected.sender_name)}
                </div>
                <div>
                  <p className="text-sm font-bold text-gray-900">{selected.sender_name}</p>
                  <p className="text-xs text-gray-400">{formatDistanceToNow(new Date(selected.created_at), { addSuffix: true })}</p>
                </div>
              </div>
              <button onClick={() => softDelete(selected.id)} className="p-2 rounded-full text-gray-400 hover:text-red-500 hover:bg-red-50 transition">
                <Trash2 size={16} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-5">
              <div className="bg-white rounded-2xl p-5 shadow-sm border border-gray-100">
                <div className="flex items-start justify-between gap-3 mb-4">
                  <h3 className="font-bold text-gray-900 text-base leading-snug">{selected.subject}</h3>
                  <span className="shrink-0 text-[10px] bg-orange-50 text-orange-600 border border-orange-100 px-2 py-1 rounded-full font-bold uppercase tracking-wider">
                    {selected.target_group}
                  </span>
                </div>
                <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">{selected.content}</p>
              </div>
            </div>
          </div>
        )}

        {/* ── Compose View ── */}
        {view === "compose" && canSend && (
          <form onSubmit={handleSend} className="flex-1 flex flex-col bg-gray-50 overflow-hidden">
            <div className="flex-1 overflow-y-auto p-5 space-y-4">
              {/* To */}
              <div>
                <div className="flex items-center justify-between mb-1.5">
                  <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider">To (Target Group)</label>
                  {isSuperAdmin && (
                    <button
                      type="button"
                      onClick={() => setShowGroupInput(v => !v)}
                      className="text-[10px] text-[#f08a4b] font-bold hover:underline"
                    >
                      {showGroupInput ? "Cancel" : "+ New Group"}
                    </button>
                  )}
                </div>

                {/* Grouped Select */}
                <select
                  value={targetGroup}
                  onChange={e => setTargetGroup(e.target.value)}
                  className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm bg-white focus:outline-none focus:border-[#f08a4b] focus:ring-2 focus:ring-[#f08a4b]/20 transition"
                >
                  <optgroup label="── Essential ──">
                    <option value="All Employees">All Employees</option>
                    <option value="All">Everyone (Global)</option>
                  </optgroup>
                  {departments.length > 0 && (
                    <optgroup label="── Departments ──">
                      {departments.map(d => <option key={d} value={d}>{d}</option>)}
                    </optgroup>
                  )}
                  {customGroups.length > 0 && (
                    <optgroup label="── Custom Groups ──">
                      {customGroups.map(g => <option key={g.id} value={g.name}>{g.name}</option>)}
                    </optgroup>
                  )}
                </select>

                {/* Superadmin: Create new group inline */}
                {showGroupInput && isSuperAdmin && (
                  <div className="mt-2 flex gap-2 items-center">
                    <input
                      type="text"
                      placeholder="New group name…"
                      maxLength={100}
                      value={newGroupName}
                      onChange={e => setNewGroupName(e.target.value)}
                      className="flex-1 border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:border-[#f08a4b]"
                    />
                    <button
                      type="button"
                      disabled={addingGroup || !newGroupName.trim()}
                      onClick={async () => {
                        setAddingGroup(true);
                        try {
                          const res = await apiFetch("/messages/groups", {
                            method: "POST",
                            body: JSON.stringify({ name: newGroupName.trim() }),
                          });
                          if (res.ok) {
                            const g = await res.json();
                            setCustomGroups(prev => [...prev, g]);
                            setTargetGroup(g.name);
                            setNewGroupName("");
                            setShowGroupInput(false);
                          } else {
                            const err = await res.json();
                            await showAlert(formatApiError(err.detail, "Failed to create group"), { title: "Couldn't create group" });
                          }
                        } finally { setAddingGroup(false); }
                      }}
                      className="px-3 py-2 bg-[#f08a4b] text-white rounded-lg text-xs font-bold disabled:opacity-50 hover:bg-[#e47d3d] transition"
                    >
                      {addingGroup ? "…" : "Add"}
                    </button>
                  </div>
                )}

                {/* Superadmin: List + delete custom groups */}
                {isSuperAdmin && customGroups.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {customGroups.map(g => (
                      <span key={g.id} className="flex items-center gap-1 bg-orange-50 border border-orange-100 text-orange-700 text-[11px] font-semibold px-2 py-1 rounded-full">
                        {g.name}
                        <button
                          type="button"
                          onClick={async () => {
                            const ok = await showConfirm(`The "${g.name}" group will be permanently deleted.`, {
                              title: "Delete this group?",
                              confirmText: "Delete",
                            });
                            if (!ok) return;
                            await apiFetch(`/messages/groups/${g.id}`, { method: "DELETE" });
                            setCustomGroups(prev => prev.filter(x => x.id !== g.id));
                            if (targetGroup === g.name) setTargetGroup("All Employees");
                          }}
                          className="ml-0.5 text-orange-400 hover:text-red-500 transition"
                        >
                          ×
                        </button>
                      </span>
                    ))}
                  </div>
                )}
              </div>

              {/* Subject */}
              <div>
                <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider mb-1.5">Subject</label>
                <input
                  type="text"
                  required
                  placeholder="Enter subject…"
                  value={subject}
                  maxLength={200}
                  onChange={e => setSubject(e.target.value)}
                  className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm bg-white focus:outline-none focus:border-[#f08a4b] focus:ring-2 focus:ring-[#f08a4b]/20 transition"
                />
              </div>

              {/* Body */}
              <div>
                <label className="block text-xs font-bold text-gray-500 uppercase tracking-wider mb-1.5">Message</label>
                <textarea
                  required
                  placeholder="Write your message…"
                  value={body}
                  maxLength={10000}
                  onChange={e => setBody(e.target.value)}
                  rows={10}
                  className="w-full border border-gray-200 rounded-xl px-3 py-2.5 text-sm bg-white focus:outline-none focus:border-[#f08a4b] focus:ring-2 focus:ring-[#f08a4b]/20 resize-none transition"
                />
              </div>
            </div>

            <div className="flex-shrink-0 bg-white border-t border-gray-100 px-5 py-4 flex items-center justify-between">
              <button type="button" onClick={() => setView("list")} className="text-sm text-gray-500 hover:text-gray-700 font-medium transition">
                Cancel
              </button>
              <button
                type="submit"
                disabled={sending || !subject.trim() || !body.trim()}
                className="flex items-center gap-2 bg-[#f08a4b] hover:bg-[#e47d3d] disabled:opacity-50 text-white px-6 py-2.5 rounded-xl text-sm font-bold transition"
              >
                {sending ? "Sending…" : <><Send size={14} /> Send Message</>}
              </button>
            </div>
          </form>
        )}
      </div>
    </>
  );
}
