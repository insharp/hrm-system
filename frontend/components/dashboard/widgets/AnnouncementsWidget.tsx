"use client";

import { useRouter } from "next/navigation";
import { Bell, Plus, Pencil, Trash2, X, Check } from "lucide-react";
import { useEffect, useState } from "react";
import { apiFetch, formatApiError } from "@/lib/api";
import ModalPortal from "@/components/ModalPortal";
import { useDialog } from "@/context/dialog-context";

interface Announcement {
  id: number;
  title: string;
  content: string;
  created_at: string;
}

interface Props { permissions: string[] }

export default function AnnouncementsWidget({ permissions }: Props) {
  const router = useRouter();
  const canManage = permissions.includes("widget.announcements.manage");
  const { showAlert, showConfirm } = useDialog();

  const [items, setItems] = useState<Announcement[]>([]);
  const [loading, setLoading] = useState(true);

  const [modalOpen, setModalOpen] = useState(false);
  const [editItem, setEditItem] = useState<Announcement | null>(null);
  const [formTitle, setFormTitle] = useState("");
  const [formContent, setFormContent] = useState("");
  const [saving, setSaving] = useState(false);

  const load = async () => {
    try {
      const res = await apiFetch("/announcements");
      if (res.ok) setItems(await res.json());
    } catch (e) { console.error(e); }
    finally { setLoading(false); }
  };

  useEffect(() => { load(); }, []);

  const openCreate = () => { setEditItem(null); setFormTitle(""); setFormContent(""); setModalOpen(true); };
  const openEdit = (a: Announcement, e: React.MouseEvent) => { e.stopPropagation(); setEditItem(a); setFormTitle(a.title); setFormContent(a.content); setModalOpen(true); };
  const handleDelete = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation();
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
      const endpoint = editItem ? `/announcements/${editItem.id}` : "/announcements";
      const method = editItem ? "PUT" : "POST";
      const res = await apiFetch(endpoint, {
        method,
        body: JSON.stringify({ title: formTitle.trim(), content: formContent.trim() })
      });
      
      if (res.ok) {
        setModalOpen(false);
        setEditItem(null);
        load();
      } else {
        const err = await res.json();
        await showAlert(formatApiError(err.detail, "Failed to save announcement"), { title: "Couldn't save announcement" });
      }
    } catch (e) {
      console.error(e);
      await showAlert("Could not connect to the server.", { title: "Network error" });
    } finally { setSaving(false); }
  };

  const timeAgo = (d: string) => {
    const diff = Date.now() - new Date(d).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 60) return `${m}m ago`;
    const h = Math.floor(m / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  };

  return (
    <>
      <div
        className="bg-white border border-gray-200 rounded-2xl p-6 shadow-sm h-full w-full flex flex-col"
      >
        {/* Header */}
        <div className="flex justify-between items-center mb-5">
          <h3 className="text-base font-semibold text-gray-800">Announcements</h3>
          <div className="flex items-center gap-2">
            {canManage && (
              <button
                onClick={(e) => { e.stopPropagation(); openCreate(); }}
                className="w-6 h-6 rounded-full bg-[#F2924E] text-white flex items-center justify-center hover:bg-orange-500 transition"
                title="New announcement"
              >
                <Plus size={12} />
              </button>
            )}
            <Bell size={16} className="text-gray-400" />
          </div>
        </div>

        {/* Items */}
        <div className="space-y-4 flex-1">
          {loading ? (
            <p className="text-xs text-gray-400">Loading…</p>
          ) : items.length === 0 ? (
            <p className="text-xs text-gray-400">No announcements yet.</p>
          ) : (
            items.slice(0, 3).map((a) => (
              <div key={a.id} className="flex items-start justify-between gap-2">
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-800 truncate">{a.title}</p>
                  <p className="text-xs text-gray-400 mt-0.5">{timeAgo(a.created_at)}</p>
                </div>
                {canManage && (
                  <div className="flex items-center gap-1 flex-shrink-0">
                    <button onClick={(e) => openEdit(a, e)} className="p-1 text-gray-400 hover:text-blue-500 transition">
                      <Pencil size={12} />
                    </button>
                    <button onClick={(e) => handleDelete(a.id, e)} className="p-1 text-gray-400 hover:text-red-500 transition">
                      <Trash2 size={12} />
                    </button>
                  </div>
                )}
              </div>
            ))
          )}
        </div>

        <div className="mt-auto pt-4 border-t border-gray-100 flex justify-end">
          <button 
            onClick={() => router.push("/dashboard/announcements")}
            className="text-[#f2924e] text-[10px] font-bold uppercase tracking-wider hover:underline"
          >
            View All
          </button>
        </div>
      </div>

      {/* Modal */}
      <ModalPortal open={modalOpen} onClose={() => setModalOpen(false)}>
          <div className="bg-white rounded-2xl shadow-2xl w-[480px] p-8">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-lg font-semibold text-gray-900">{editItem ? "Edit Announcement" : "New Announcement"}</h2>
              <button onClick={() => setModalOpen(false)} className="text-gray-400 hover:text-gray-600"><X size={18} /></button>
            </div>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Title</label>
                <input className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/40" value={formTitle} onChange={(e) => setFormTitle(e.target.value)} maxLength={200} placeholder="Announcement title" />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700 mb-1">Content</label>
                <textarea className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-[#F2924E]/40 resize-none" rows={4} value={formContent} onChange={(e) => setFormContent(e.target.value)} maxLength={5000} placeholder="Write your announcement…" />
              </div>
            </div>
            <div className="flex justify-end gap-3 mt-6">
              <button onClick={() => setModalOpen(false)} className="text-sm font-medium text-gray-600 px-4 py-2">Cancel</button>
              <button onClick={handleSave} disabled={saving || !formTitle.trim() || !formContent.trim()} className="flex items-center gap-1.5 bg-[#F2924E] hover:bg-orange-500 disabled:opacity-50 text-white text-sm font-medium px-5 py-2 rounded-lg transition">
                <Check size={14} /> {saving ? "Saving…" : "Save"}
              </button>
            </div>
          </div>
      </ModalPortal>
    </>
  );
}
