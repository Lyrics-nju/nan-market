import { useState, useEffect, useCallback } from 'react';
import { Star, Shield, BookOpen, ShoppingBag, Folder, Edit3, Trash2, Search, X } from 'lucide-react';

const CAT: Record<string, { label: string; color: string; icon: any }> = {
  A: { label: '重要信息', color: '#BB00FF', icon: Shield },
  B: { label: '校园轶事', color: '#ADFF00', icon: BookOpen },
  C: { label: '二手资讯', color: '#FF5C00', icon: ShoppingBag },
};

export default function BookmarksPage() {
  const [bookmarks, setBookmarks] = useState<any[]>([]);
  const [folders, setFolders] = useState<string[]>(['默认收藏']);
  const [activeFolder, setActiveFolder] = useState('');
  const [search, setSearch] = useState('');
  const [renaming, setRenaming] = useState('');
  const [renameVal, setRenameVal] = useState('');
  const [newFolder, setNewFolder] = useState('');
  const [showNewFolder, setShowNewFolder] = useState(false);

  const fetchBookmarks = useCallback(async () => {
    const params = new URLSearchParams();
    if (activeFolder) params.set('folder', activeFolder);
    if (search) params.set('search', search);
    const res = await fetch(`/api/bookmarks?${params}`);
    setBookmarks(await res.json());
  }, [activeFolder, search]);

  const fetchFolders = useCallback(async () => {
    const res = await fetch('/api/folders');
    setFolders(await res.json());
  }, []);

  useEffect(() => { fetchBookmarks(); fetchFolders(); }, [fetchBookmarks, fetchFolders]);

  const removeBookmark = async (msgId: string) => {
    await fetch(`/api/bookmarks/${msgId}`, { method: 'DELETE' });
    fetchBookmarks();
  };

  const renameFolder = async () => {
    if (!renaming || !renameVal.trim()) return;
    await fetch('/api/folders/rename', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ old_name: renaming, new_name: renameVal.trim() }),
    });
    setRenaming('');
    fetchFolders();
    fetchBookmarks();
  };

  const deleteFolder = async (name: string) => {
    await fetch(`/api/folders/${encodeURIComponent(name)}`, { method: 'DELETE' });
    if (activeFolder === name) setActiveFolder('');
    fetchFolders();
    fetchBookmarks();
  };

  const createFolder = async () => {
    if (!newFolder.trim()) return;
    setNewFolder('');
    setShowNewFolder(false);
    fetchFolders();
  };

  return (
    <div style={{ padding: '32px 40px 32px 32px' }} className="animate-fade-in">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>我的收藏</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>管理你收藏的重要消息</p>
        </div>
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl glass">
          <Star size={18} style={{ color: 'var(--neon-cyan)' }} />
          <span className="text-sm font-mono" style={{ color: 'var(--neon-cyan)' }}>{bookmarks.length} 条</span>
        </div>
      </div>

      <div className="flex gap-6">
        {/* 左侧文件夹列表 */}
        <div className="w-56 shrink-0">
          <div className="glass rounded-2xl overflow-hidden">
            <div className="px-4 py-3 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
              <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>收藏夹</span>
              <button onClick={() => setShowNewFolder(true)} className="p-1 rounded-lg hover:bg-white/[0.06] transition-colors">
                <Folder size={16} style={{ color: 'var(--text-secondary)' }} />
              </button>
            </div>

            {showNewFolder && (
              <div className="px-3 py-2" style={{ borderBottom: '1px solid var(--border)' }}>
                <div className="flex gap-1">
                  <input value={newFolder} onChange={e => setNewFolder(e.target.value)}
                    placeholder="名称" className="flex-1 bg-white/[0.04] border border-white/[0.08] rounded-lg px-2 py-1 text-sm outline-none focus:border-cyan-500/50"
                    style={{ color: 'var(--text-primary)' }} onKeyDown={e => e.key === 'Enter' && createFolder()} />
                  <button onClick={createFolder} className="px-2 py-1 rounded-lg text-xs font-medium" style={{ background: 'rgba(0,242,255,0.1)', color: 'var(--neon-cyan)' }}>+</button>
                </div>
              </div>
            )}

            <div className="py-1">
              <button onClick={() => setActiveFolder('')}
                className={`w-full flex items-center gap-2 px-4 py-2.5 text-sm transition-colors ${activeFolder === '' ? 'bg-white/[0.06]' : 'hover:bg-white/[0.03]'}`}
                style={{ color: activeFolder === '' ? 'var(--neon-cyan)' : 'var(--text-secondary)' }}>
                <Star size={16} /> 全部收藏
              </button>
              {folders.map(f => (
                <div key={f} className={`group flex items-center gap-1 px-3 py-1 transition-colors ${activeFolder === f ? 'bg-white/[0.06]' : 'hover:bg-white/[0.03]'}`}>
                  {renaming === f ? (
                    <div className="flex-1 flex gap-1">
                      <input value={renameVal} onChange={e => setRenameVal(e.target.value)}
                        className="flex-1 bg-white/[0.04] border border-white/[0.08] rounded px-2 py-1 text-sm outline-none"
                        style={{ color: 'var(--text-primary)' }}
                        onKeyDown={e => { if (e.key === 'Enter') renameFolder(); if (e.key === 'Escape') setRenaming(''); }}
                        autoFocus />
                    </div>
                  ) : (
                    <button onClick={() => setActiveFolder(f)}
                      className="flex-1 flex items-center gap-2 py-2 text-sm text-left"
                      style={{ color: activeFolder === f ? 'var(--neon-cyan)' : 'var(--text-secondary)' }}>
                      <Folder size={14} /> {f}
                    </button>
                  )}
                  <div className="opacity-0 group-hover:opacity-100 flex gap-0.5 transition-opacity">
                    <button onClick={() => { setRenaming(f); setRenameVal(f); }} className="p-1 rounded hover:bg-white/[0.06]"><Edit3 size={12} style={{ color: 'var(--text-dim)' }} /></button>
                    <button onClick={() => deleteFolder(f)} className="p-1 rounded hover:bg-white/[0.06]"><Trash2 size={12} style={{ color: 'var(--text-dim)' }} /></button>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 右侧消息列表 */}
        <div className="flex-1 min-w-0">
          <div className="glass rounded-2xl overflow-hidden">
            {/* 搜索栏 */}
            <div className="px-5 py-4" style={{ borderBottom: '1px solid var(--border)' }}>
              <div className="flex items-center gap-3 px-4 py-2.5 rounded-xl" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)' }}>
                <Search size={18} style={{ color: 'var(--text-dim)' }} />
                <input value={search} onChange={e => setSearch(e.target.value)} placeholder="搜索收藏消息..."
                  className="flex-1 bg-transparent outline-none text-sm" style={{ color: 'var(--text-primary)' }} />
                {search && <button onClick={() => setSearch('')}><X size={16} style={{ color: 'var(--text-dim)' }} /></button>}
              </div>
            </div>

            <div className="divide-y" style={{ borderColor: 'var(--border)' }}>
              {bookmarks.length === 0 ? (
                <div className="px-6 py-16 text-center">
                  <Star size={40} style={{ color: 'var(--text-dim)' }} className="mx-auto mb-3" />
                  <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>暂无收藏</p>
                  <p className="text-xs mt-1" style={{ color: 'var(--text-dim)' }}>在消息中心收藏重要消息</p>
                </div>
              ) : bookmarks.map((msg: any, i: number) => {
                const c = CAT[msg.category] || CAT.A;
                const Icon = c.icon;
                return (
                  <div key={msg.id || i} className="px-6 py-4 flex items-start gap-4 hover:bg-white/[0.02] transition-colors">
                    <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
                         style={{ background: `${c.color}12` }}>
                      <Icon size={18} style={{ color: c.color }} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm font-medium mb-1 truncate" style={{ color: 'var(--neon-cyan)' }}>{msg.summary}</p>
                      <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-dim)' }}>
                        <span>{msg.group_name || '未知群'}</span>
                        <span>{msg.sender_name}</span>
                        <span className="font-mono">{msg.created_at?.slice(5, 16)}</span>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      <span className="text-xs font-mono px-2 py-0.5 rounded" style={{ background: `${c.color}10`, color: c.color }}>{c.label}</span>
                      <button onClick={() => removeBookmark(msg.msg_id)}
                        className="p-1.5 rounded-lg hover:bg-white/[0.06] transition-colors">
                        <Star size={16} fill="var(--neon-cyan)" style={{ color: 'var(--neon-cyan)' }} />
                      </button>
                    </div>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
