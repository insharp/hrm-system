"use client";

import { useState, useEffect } from "react";
import { useRouter } from "next/navigation";
import { ChevronRight, Bell, Plus, Pencil, Trash2, X, Check, Search } from "lucide-react";
import { apiFetch, formatApiError } from "@/lib/api";
import { useAuth } from "@/context/auth-context";
import { useDialog } from "@/context/dialog-context";

interface Announcement {
  id: number;
  title: string;
  content: string;
  created_at: string;
}

export default function AnnouncementsPage() {
  const router = useRouter();
  const { user } = useAuth();
  const { showConfirm, showAlert } = useDialog();
  const canManage = user?.permissions?.includes("widget.announcements.manage") ?? false;

  const [items, setItems] = useState<Announcement[]>([]);
  const [loading, setLoading] = useState(true);
  const [search, setSearch] = useState("");

  const [modalOpen, setModalOpen] = useState(false);
  const [editItem, setEditItem] = useState<Announcement | null>(null);
  const [formTitle, setFormTitle] = useState("");
  const [formContent, setFormContent] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    setLoading(true);
    try {
      const res = await apiFetch("/announcements");
      if (res.ok) setItems(await res.json());
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const filtered = items.filter((a) =>
    a.title.toLowerCase().includes(search.toLowerCase()) ||
    a.content.toLowerCase().includes(search.toLowerCase())
  );

  const openCreate = () => { setEditItem(null); setFormTitle(""); setFormContent(""); setModalOpen(true); };
  const openEdit = (a: Announcement) => { setEditItem(a); setFormTitle(a.title); setFormContent(a.content); setModalOpen(true); };
  const handleDelete = async (id: number) => {
    const ok = await showConfirm("This announcement will be permanently deleted.", {
      title: "Delete this announcement?",
      confirmText: "Delete",
    });
    if (!ok) return;
    await apiFetch(`/announcements/${id}`, { method: "DELETE" });
    load();
  };
  const handleSave = async () => {
    setSaving(true);
    try {
      const body = JSON.stringify({ title: formTitle.trim(), content: formContent.trim() });
      const res = editItem
        ? await apiFetch(`/announcements/${editItem.id}`, { method: "PUT", body })
        : await apiFetch("/announcements", { method: "POST", body });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        await showAlert(formatApiError(err.detail, "Failed to save announcement"), { title: "Couldn't save announcement" });
        return;
      }
      setModalOpen(false);
      load();
    } catch {
      await showAlert("Could not connect to the server.", { title: "Network error" });
    } finally { setSaving(false); }
  };

  const fmtDate = (d: string) =>
    new Date(d).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });

  return (
    <div className="flex flex-col gap-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-sm text-gray-500">
        <button onClick={() => router.push("/dashboard")} className="hover:text-[#F2924E] transition">Dashboard</button>
        <ChevronRight size={14} />
        <span className="text-gray-800 font-medium">Announcements</span>
      </nav>

      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-gray-900 flex items-center gap-2">
            <Bell size={22} className="text-[#F2924E]" /> Announcements
          </h1>
          <p className="text-sm text-gray-500 mt-1">Company-wide announcements visible to all employees</p>
        </div>
        {canManage && (
          <button onClick={openCreate} className="flex items-center gap-2 bg-[#F2924E] hover:bg-orange-500 text-white text-sm font-medium px-5 py-2.5 rounded-xl transition shadow-sm">
            <Plus size={16} /> New Announcement
          </button>
        )}
      </div>

      {/* Search */}
      <div className="relative w-full max-w-sm">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400" />
        <input
          value={search} onChange={(e) => setSearch(e.target.value)}
          placeholder="Search announcements…"
          className="w-full pl-9 pr-4 py-2.5 text-sm border border-gray-200 rounded-xl focus:outline-none focus:ring-2 focus:ring-[#F2924E]/30"
        />
      </div>

      {/* List */}
      <div className="space-y-4">
        {loading ? (
          Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="bg-white border border-gray-200 rounded-2xl p-6 animate-pulse h-24" />
          ))
        ) : filtered.length === 0 ? (
          <div className="bg-white border border-gray-200 rounded-2xl p-12 text-center">
            <Bell size={32} className="text-gray-200 mx-auto mb-3" />
            <p className="text-gray-500 font-medium">No announcements found</p>
            {canManage && <p className="text-sm text-gray-400 mt-1">Click &quot;New Announcement&quot; to create one</p>}
          </div>
        ) : (
          filtered.map((a) => (
            <div key={a.id} className="bg-white border border-gray-200 rounded-2xl p-6 hover:shadow-sm transition">
              <div className="flex items-start justify-between gap-4">
                <div className="flex-1">
                  <h3 className="text-base font-semibold text-gray-900 mb-1">{a.title}</h3>
                  <p className="text-sm text-gray-600 leading-relaxed">{a.content}</p>
                  <p className="text-xs text-gray-400 mt-3">{fmtDate(a.created_at)}</p>
                </div>
                {canManage && (
                  <div className="flex gap-2 flex-shrink-0">
                    <button onClick={() => openEdit(a)} className="p-2 text-gray-400 hover:text-blue-500 border border-gray-200 rounded-lg transition">
                      <Pencil size={14} />
                    </button>
                    <button onClick={() => handleDelete(a.id)} className="p-2 text-gray-400 hover:text-red-500 border border-gray-200 rounded-lg transition">
                      <Trash2 size={14} />
                    </button>
                  </div>
                )}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Modal */}
      {modalOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center" onClick={() => setModalOpen(false)}>
          <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" />
          <div className="relative bg-white rounded-2xl shadow-2xl w-[560px] p-8 z-10" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold text-gray-900">{editItem ? "Edit Announcement" : "New Announcement"}</h2>
              <button onClick={() => setModalOpen(false)} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Title</label>
                <input
                  className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/30"
                  value={formTitle} onChange={(e) => setFormTitle(e.target.value)} maxLength={200} placeholder="Announcement title"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Content</label>
                <textarea
                  className="w-full border border-gray-200 rounded-xl px-4 py-2.5 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/30 resize-none"
                  rows={5} value={formContent} onChange={(e) => setFormContent(e.target.value)} maxLength={5000} placeholder="Write your message…"
                />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setModalOpen(false)} className="text-sm font-medium text-gray-600 px-4 py-2">Cancel</button>
              <button onClick={handleSave} disabled={saving || !formTitle.trim() || !formContent.trim()} className="flex items-center gap-1.5 bg-[#F2924E] hover:bg-orange-500 disabled:opacity-50 text-white text-sm font-medium px-6 py-2.5 rounded-xl transition">
                <Check size={14} /> {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}