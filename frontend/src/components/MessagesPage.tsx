import { useState, useEffect, useRef, useCallback } from 'react';
import {
  Shield, BookOpen, ShoppingBag, ChevronDown, Layers,
  Star, Trash2, CheckSquare, Square, Search, Calendar,
  Activity, Loader2, CheckCircle2, Package, Cpu, Zap,
  FolderOpen, ChevronRight,
} from 'lucide-react';

/* ── 类型 ──────────────────────────────────────────────── */
interface Msg {
  id: number; msg_id: string; chat_type: string; group_id: string;
  group_name: string; sender_id: string; sender_name: string;
  raw_content: string; category: 'A' | 'B' | 'C'; summary: string;
  tags: string[]; created_at: string; bookmarked?: boolean;
}
interface Stats { total: number; A: number; B: number; C: number; }
interface FolderInfo { name: string; count: number; }

const CAT = {
  A: { label: '重要信息', color: '#BB00FF', glow: 'animate-pulse-glow-purple', icon: Shield },
  B: { label: '校园轶事', color: '#ADFF00', glow: 'animate-pulse-glow-green',  icon: BookOpen },
  C: { label: '二手资讯', color: '#FF5C00', glow: 'animate-pulse-glow-orange', icon: ShoppingBag },
};

const TIME_OPTIONS = [
  { label: '一周', days: 7 }, { label: '一月', days: 30 },
  { label: '三月', days: 90 }, { label: '半年', days: 180 }, { label: '全部', days: 0 },
];

/* ── 消息卡片 ──────────────────────────────────────────── */
function MessageCard({ msg, selected, onSelect, onDelete, onBookmark }: {
  msg: Msg; selected: boolean; onSelect: (id: number) => void;
  onDelete: (id: number) => void; onBookmark: (msgId: string, bookmarked: boolean) => void;
}) {
  const [expanded, setExpanded] = useState(false);
  const c = CAT[msg.category];
  const isBatch = msg.raw_content?.startsWith('[批量]');
  const batchData = isBatch ? (() => { try { return JSON.parse(msg.raw_content.replace('[批量] ', '')); } catch { return null; } })() : null;

  return (
    <div className={`glass glass-hover rounded-xl relative overflow-hidden transition-all duration-300 ${c.glow}`}
         style={{ borderLeft: `4px solid ${c.color}` }}>
      <div className="p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2.5">
            <button onClick={() => onSelect(msg.id)} className="hover:opacity-80 transition-opacity">
              {selected ? <CheckSquare size={18} style={{ color: 'var(--neon-cyan)' }} />
                        : <Square size={18} style={{ color: 'var(--text-dim)' }} />}
            </button>
            {isBatch && (
              <span className="text-xs font-mono px-2 py-1 rounded flex items-center gap-1"
                    style={{ background: 'rgba(0, 242, 255, 0.1)', color: 'var(--neon-cyan)', border: '1px solid rgba(0, 242, 255, 0.25)' }}>
                <Layers size={11} /> 批量情报
              </span>
            )}
            <span className="text-xs font-mono px-2 py-1 rounded"
                  style={{ background: `${c.color}15`, color: c.color, border: `1px solid ${c.color}30` }}>
              {c.label}
            </span>
            <span className="text-xs font-mono" style={{ color: 'var(--text-dim)' }}>{msg.created_at}</span>
          </div>
          <div className="flex items-center gap-1.5">
            <button onClick={() => onBookmark(msg.msg_id, !!msg.bookmarked)}
                    className="p-1.5 rounded-lg hover:bg-white/[0.06] transition-colors" title={msg.bookmarked ? '取消收藏' : '收藏'}>
              <Star size={16} fill={msg.bookmarked ? '#FFD700' : 'none'} style={{ color: msg.bookmarked ? '#FFD700' : 'var(--text-dim)' }} />
            </button>
            <button onClick={() => onDelete(msg.id)}
                    className="p-1.5 rounded-lg hover:bg-white/[0.06] transition-colors" title="删除">
              <Trash2 size={16} style={{ color: 'var(--text-dim)' }} />
            </button>
          </div>
        </div>

        <p className="text-lg font-bold leading-snug mb-3" style={{ color: 'var(--neon-cyan)' }}>
          {isBatch && batchData ? batchData.title : msg.summary}
        </p>
        {isBatch && msg.summary && <p className="text-sm leading-relaxed mb-3" style={{ color: 'var(--text-secondary)' }}>{msg.summary}</p>}

        {msg.tags?.length > 0 && (
          <div className="flex flex-wrap gap-2 mb-3">
            {msg.tags.map((tag, i) => (
              <span key={i} className="text-xs font-mono px-2.5 py-1 rounded-full"
                    style={{ background: 'transparent', color: c.color, border: `1px solid ${c.color}40` }}>#{tag}</span>
            ))}
          </div>
        )}

        <button onClick={() => setExpanded(!expanded)} className="flex items-center gap-1.5 text-xs transition-colors hover:opacity-80" style={{ color: 'var(--text-dim)' }}>
          <ChevronDown size={13} className={`transition-transform ${expanded ? 'rotate-180' : ''}`} />
          {isBatch ? '查看上下文详情' : '原始数据'}
        </button>

        {expanded && (
          <div className="mt-3 rounded-lg font-mono animate-fade-in overflow-hidden"
               style={{ background: 'rgba(0,0,0,0.6)', border: '1px solid rgba(255,255,255,0.06)' }}>
            {isBatch && batchData?.messages ? (
              <div className="max-h-80 overflow-y-auto">
                {batchData.messages.map((m: any, i: number) => (
                  <div key={i} className="px-3 py-1 flex items-baseline gap-1 hover:bg-white/[0.03] transition-colors"
                       style={{ borderBottom: '1px solid rgba(255,255,255,0.02)', fontSize: '12px', lineHeight: '20px' }}>
                    <span style={{ color: 'var(--neon-cyan)', fontSize: '11px', fontWeight: 600 }}>[{msg.group_name || '未知'}]</span>
                    <span style={{ color: 'var(--neon-green)', fontSize: '11px', fontWeight: 600 }}>{m.sender}</span>
                    <span style={{ color: 'rgba(255,255,255,0.25)', fontSize: '11px' }}>({m.time?.slice(5, 16) || ''})</span>
                    <span style={{ color: 'rgba(255,255,255,0.15)', fontSize: '11px' }}>: </span>
                    <span className="break-all" style={{ color: 'rgba(255,255,255,0.85)', fontSize: '12px' }}>{m.content}</span>
                  </div>
                ))}
              </div>
            ) : (
              <div className="px-3 py-2" style={{ fontSize: '12px', lineHeight: '20px' }}>
                <span style={{ color: 'var(--neon-green)', fontWeight: 600 }}>{msg.sender_name}</span>
                <span style={{ color: 'rgba(255,255,255,0.25)' }}> ({msg.sender_id})</span>
                <span style={{ color: 'rgba(255,255,255,0.15)' }}>: </span>
                <span className="break-all" style={{ color: 'rgba(255,255,255,0.85)' }}>{msg.raw_content}</span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

/* ── Toast ─────────────────────────────────────────────── */
function Toast({ message, onDone }: { message: string; onDone: () => void }) {
  useEffect(() => { const t = setTimeout(onDone, 4000); return () => clearTimeout(t); }, [onDone]);
  return (
    <div className="fixed bottom-8 left-1/2 -translate-x-1/2 z-50 animate-fade-in">
      <div className="glass rounded-xl px-6 py-3 flex items-center gap-3 font-mono text-sm"
           style={{ border: '1px solid rgba(0, 242, 255, 0.3)', boxShadow: '0 0 20px rgba(0, 242, 255, 0.15)' }}>
        <CheckCircle2 size={18} style={{ color: 'var(--neon-cyan)' }} />
        <span style={{ color: 'var(--neon-cyan)' }}>{message}</span>
      </div>
    </div>
  );
}

/* ── 主页面 ────────────────────────────────────────────── */
export default function MessagesPage() {
  const [tab, setTab] = useState<'A' | 'B' | 'C'>('A');
  const [messages, setMessages] = useState<Msg[]>([]);
  const [stats, setStats] = useState<Stats>({ total: 0, A: 0, B: 0, C: 0 });
  const [mode, setMode] = useState('realtime');
  const [bufferCount, setBufferCount] = useState(0);
  const [processing, setProcessing] = useState(false);
  const [toast, setToast] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [searchInput, setSearchInput] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [daysFilter, setDaysFilter] = useState(0);
  const [viewMode, setViewMode] = useState<'messages' | 'bookmarks'>('messages');
  const [folders, setFolders] = useState<FolderInfo[]>([]);
  const [activeFolder, setActiveFolder] = useState<string | null>(null);
  const [showFolderDropdown, setShowFolderDropdown] = useState(false);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');
  const listRef = useRef<HTMLDivElement>(null);

  const fetchMessages = useCallback(async () => {
    try {
      const params = new URLSearchParams({ category: tab, limit: '80' });
      if (searchQuery) params.set('search', searchQuery);
      if (daysFilter > 0) params.set('days', String(daysFilter));
      if (viewMode === 'bookmarks' && activeFolder) params.set('folder', activeFolder);
      const res = await fetch(`/api/messages?${params}`);
      let data = await res.json();
      if (viewMode === 'bookmarks') data = data.filter((m: Msg) => m.bookmarked);
      setMessages(data);
    } catch {}
  }, [tab, searchQuery, daysFilter, viewMode, activeFolder]);

  const fetchStats = useCallback(async () => { try { setStats(await (await fetch('/api/stats')).json()); } catch {} }, []);
  const fetchFolders = useCallback(async () => { try { setFolders(await (await fetch('/api/folders')).json()); } catch {} }, []);
  const fetchConfig = useCallback(async () => { try { setMode((await (await fetch('/api/config')).json()).scraper_mode || 'realtime'); } catch {} }, []);
  const fetchBufferStats = useCallback(async () => { try { setBufferCount((await (await fetch('/api/buffer_stats')).json()).buffered || 0); } catch {} }, []);

  useEffect(() => { fetchMessages(); fetchStats(); fetchConfig(); fetchFolders(); }, [fetchMessages, fetchStats, fetchConfig, fetchFolders]);
  useEffect(() => { const t = setTimeout(() => setSearchQuery(searchInput), 400); return () => clearTimeout(t); }, [searchInput]);
  useEffect(() => { const iv = setInterval(fetchBufferStats, 4000); return () => clearInterval(iv); }, [fetchBufferStats]);

  useEffect(() => {
    const es = new EventSource('/api/stream');
    es.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data);
        if (evt.type === 'new_message') {
          const m = evt.data as Msg;
          setStats(prev => ({ total: prev.total + 1, A: prev.A + (m.category === 'A' ? 1 : 0), B: prev.B + (m.category === 'B' ? 1 : 0), C: prev.C + (m.category === 'C' ? 1 : 0) }));
          if (m.category === tab && viewMode === 'messages' && !searchQuery) setMessages(prev => [m, ...prev]);
        }
      } catch {}
    };
    return () => es.close();
  }, [tab, viewMode, searchQuery]);

  useEffect(() => { listRef.current?.scrollTo({ top: 0, behavior: 'smooth' }); }, [messages.length]);

  const toggleSelect = (id: number) => setSelectedIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  const toggleSelectAll = () => setSelectedIds(selectedIds.size === messages.length ? new Set() : new Set(messages.map(m => m.id)));

  const handleDelete = async (id: number) => {
    await fetch(`/api/messages/${id}`, { method: 'DELETE' });
    setMessages(prev => prev.filter(m => m.id !== id));
    fetchStats();
    setToast('已删除');
  };

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    const res = await fetch('/api/messages/delete_batch', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ ids: Array.from(selectedIds) }) });
    const data = await res.json();
    setMessages(prev => prev.filter(m => !selectedIds.has(m.id)));
    fetchStats(); setSelectedIds(new Set()); setToast(`已删除 ${data.deleted} 条消息`);
  };

  const handleBookmark = async (msgId: string, currentlyBookmarked: boolean) => {
    if (currentlyBookmarked) await fetch(`/api/bookmarks/${msgId}`, { method: 'DELETE' });
    else await fetch('/api/bookmarks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ msg_id: msgId, folder: activeFolder || '默认收藏' }) });
    setMessages(prev => prev.map(m => m.msg_id === msgId ? { ...m, bookmarked: !currentlyBookmarked } : m));
    fetchFolders();
  };

  const handleBatchBookmark = async () => {
    if (selectedIds.size === 0) return;
    const folder = activeFolder || '默认收藏';
    for (const id of selectedIds) {
      const msg = messages.find(m => m.id === id);
      if (msg && !msg.bookmarked) await fetch('/api/bookmarks', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ msg_id: msg.msg_id, folder }) });
    }
    fetchMessages(); setSelectedIds(new Set()); setToast(`已收藏 ${selectedIds.size} 条消息到「${folder}」`);
  };

  const handleModeSwitch = async (newMode: string) => {
    setMode(newMode);
    await fetch('/api/config', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ scraper_mode: newMode }) });
  };

  const handleBatchProcess = async () => {
    if (processing || bufferCount === 0) return;
    setProcessing(true);
    try {
      const res = await fetch('/api/batch_process', { method: 'POST' });
      const data = await res.json();
      if (data.status === 'ok') { setToast(`数据提炼完成 — ${data.topics} 个话题从 ${data.processed} 条消息中提取`); setBufferCount(0); fetchMessages(); fetchStats(); }
    } catch { setToast('批量处理失败'); } finally { setProcessing(false); }
  };

  const tabs = [
    { key: 'A' as const, label: '重要信息', color: '#BB00FF' },
    { key: 'B' as const, label: '校园轶事', color: '#ADFF00' },
    { key: 'C' as const, label: '二手资讯', color: '#FF5C00' },
  ];
  const allSelected = messages.length > 0 && selectedIds.size === messages.length;

  return (
    <div style={{ padding: '32px 40px 32px 32px' }}>
      {/* 头部 */}
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>消息中心</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>管理所有采集的社群情报</p>
        </div>
        <div className="flex items-center gap-3">
          {mode === 'batch' && (
            <button onClick={handleBatchProcess} disabled={processing || bufferCount === 0}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl font-mono text-sm transition-all duration-300"
              style={{
                background: bufferCount > 0 ? 'rgba(0, 242, 255, 0.08)' : 'rgba(255,255,255,0.02)',
                border: `1px solid ${bufferCount > 0 ? 'rgba(0, 242, 255, 0.3)' : 'var(--border)'}`,
                color: bufferCount > 0 ? 'var(--neon-cyan)' : 'var(--text-dim)',
                animation: bufferCount > 0 ? 'breathe 2s ease-in-out infinite' : 'none',
              }}>
              {processing ? <><Loader2 size={16} className="animate-spin" /> 提炼中...</>
                : <><Cpu size={16} /> 聚合: {bufferCount} 条</>}
            </button>
          )}
          <div className="flex items-center rounded-xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)' }}>
            <button onClick={() => handleModeSwitch('realtime')}
              className="flex items-center gap-1.5 px-4 py-2 text-sm font-mono transition-all"
              style={{ background: mode === 'realtime' ? 'rgba(0, 242, 255, 0.1)' : 'transparent', color: mode === 'realtime' ? 'var(--neon-cyan)' : 'var(--text-dim)' }}>
              <Zap size={14} /> 实时流
            </button>
            <button onClick={() => handleModeSwitch('batch')}
              className="flex items-center gap-1.5 px-4 py-2 text-sm font-mono transition-all"
              style={{ background: mode === 'batch' ? 'rgba(0, 242, 255, 0.1)' : 'transparent', color: mode === 'batch' ? 'var(--neon-cyan)' : 'var(--text-dim)' }}>
              <Package size={14} /> 积攒
            </button>
          </div>
        </div>
      </div>

      {/* 工具栏 */}
      <div className="flex flex-wrap items-center gap-3 mb-5">
        <div className="relative flex-1 min-w-[180px] max-w-md">
          <Search size={16} className="absolute left-3.5 top-1/2 -translate-y-1/2" style={{ color: 'var(--text-dim)' }} />
          <input type="text" value={searchInput} onChange={e => setSearchInput(e.target.value)} placeholder="搜索消息..."
            className="w-full pl-10 pr-4 py-2.5 rounded-xl text-sm outline-none"
            style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)', color: 'var(--text-primary)' }} />
        </div>
        <div className="flex items-center rounded-xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)' }}>
          <Calendar size={14} className="ml-2.5" style={{ color: 'var(--text-dim)' }} />
          {TIME_OPTIONS.map(opt => (
            <button key={opt.days} onClick={() => setDaysFilter(opt.days)}
              className="px-3 py-2 text-xs font-mono transition-all"
              style={{ background: daysFilter === opt.days ? 'rgba(0, 242, 255, 0.1)' : 'transparent', color: daysFilter === opt.days ? 'var(--neon-cyan)' : 'var(--text-dim)' }}>
              {opt.label}
            </button>
          ))}
        </div>
        <div className="flex items-center rounded-xl overflow-hidden" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)' }}>
          <button onClick={() => { setViewMode('messages'); setActiveFolder(null); }}
            className="flex items-center gap-1.5 px-4 py-2 text-xs font-mono transition-all"
            style={{ background: viewMode === 'messages' ? 'rgba(0, 242, 255, 0.1)' : 'transparent', color: viewMode === 'messages' ? 'var(--neon-cyan)' : 'var(--text-dim)' }}>
            <Activity size={14} /> 全部
          </button>
          <button onClick={() => { setViewMode('bookmarks'); setActiveFolder(null); }}
            className="flex items-center gap-1.5 px-4 py-2 text-xs font-mono transition-all"
            style={{ background: viewMode === 'bookmarks' ? 'rgba(255, 215, 0, 0.1)' : 'transparent', color: viewMode === 'bookmarks' ? '#FFD700' : 'var(--text-dim)' }}>
            <Star size={14} /> 收藏
          </button>
        </div>
        {folders.length > 0 && (
          <div className="relative">
            <button onClick={() => setShowFolderDropdown(!showFolderDropdown)}
              className="flex items-center gap-1.5 px-4 py-2 rounded-xl text-xs font-mono"
              style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)', color: 'var(--text-secondary)' }}>
              <FolderOpen size={14} /> {activeFolder || '收藏夹'}
              <ChevronRight size={11} className={`transition-transform ${showFolderDropdown ? 'rotate-90' : ''}`} />
            </button>
            {showFolderDropdown && (
              <div className="absolute top-full left-0 mt-1 rounded-xl overflow-hidden z-20 min-w-[160px]"
                   style={{ background: 'rgba(10,10,15,0.95)', border: '1px solid var(--border)', backdropFilter: 'blur(20px)' }}>
                <button onClick={() => { setActiveFolder(null); setShowFolderDropdown(false); setViewMode('messages'); }}
                  className="w-full text-left px-4 py-2.5 text-sm font-mono hover:bg-white/[0.05]" style={{ color: 'var(--text-secondary)' }}>全部消息</button>
                {folders.map(f => (
                  <button key={f.name} onClick={() => { setActiveFolder(f.name); setViewMode('bookmarks'); setShowFolderDropdown(false); }}
                    className="w-full text-left px-4 py-2.5 text-sm font-mono hover:bg-white/[0.05] flex items-center justify-between"
                    style={{ color: activeFolder === f.name ? '#FFD700' : 'var(--text-secondary)' }}>
                    <span>{f.name}</span><span className="opacity-50">{f.count}</span>
                  </button>
                ))}
                <div style={{ borderTop: '1px solid var(--border)' }}>
                  {showNewFolder ? (
                    <div className="flex items-center px-3 py-2 gap-1">
                      <input type="text" value={newFolderName} onChange={e => setNewFolderName(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Enter' && newFolderName.trim()) { setActiveFolder(newFolderName.trim()); setViewMode('bookmarks'); setShowFolderDropdown(false); setShowNewFolder(false); setNewFolderName(''); } }}
                        placeholder="新收藏夹名..." className="flex-1 px-2 py-1 rounded text-sm outline-none"
                        style={{ background: 'rgba(255,255,255,0.06)', border: '1px solid var(--border)', color: 'var(--text-primary)' }} autoFocus />
                    </div>
                  ) : (
                    <button onClick={() => setShowNewFolder(true)}
                      className="w-full text-left px-4 py-2.5 text-sm font-mono hover:bg-white/[0.05]" style={{ color: 'var(--neon-cyan)' }}>+ 新建收藏夹</button>
                  )}
                </div>
              </div>
            )}
          </div>
        )}
      </div>

      {/* 批量操作栏 */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-4 mb-5 px-5 py-3 rounded-xl animate-fade-in"
             style={{ background: 'rgba(0, 242, 255, 0.06)', border: '1px solid rgba(0, 242, 255, 0.2)' }}>
          <button onClick={toggleSelectAll} className="flex items-center gap-1.5 text-sm font-mono" style={{ color: 'var(--neon-cyan)' }}>
            {allSelected ? <CheckSquare size={16} /> : <Square size={16} />} {allSelected ? '取消全选' : '全选'}
          </button>
          <span className="text-sm font-mono" style={{ color: 'var(--text-dim)' }}>已选 {selectedIds.size} 条</span>
          <div className="flex-1" />
          <button onClick={handleBatchBookmark} className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-mono hover:opacity-80"
            style={{ background: 'rgba(255, 215, 0, 0.1)', color: '#FFD700', border: '1px solid rgba(255, 215, 0, 0.2)' }}>
            <Star size={14} /> 收藏
          </button>
          <button onClick={handleBatchDelete} className="flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-mono hover:opacity-80"
            style={{ background: 'rgba(255, 51, 51, 0.1)', color: '#FF3333', border: '1px solid rgba(255, 51, 51, 0.2)' }}>
            <Trash2 size={14} /> 删除
          </button>
          <button onClick={() => setSelectedIds(new Set())} className="text-sm font-mono hover:opacity-80" style={{ color: 'var(--text-dim)' }}>取消</button>
        </div>
      )}

      {/* Tab 导航 */}
      <div className="flex gap-1.5 mb-6 p-1.5 rounded-xl" style={{ background: 'rgba(255,255,255,0.02)' }}>
        {tabs.map(t => (
          <button key={t.key} onClick={() => { setTab(t.key); setSelectedIds(new Set()); }}
            className="flex-1 py-2.5 rounded-lg text-base font-medium transition-all duration-200"
            style={{ background: tab === t.key ? `${t.color}12` : 'transparent', color: tab === t.key ? t.color : 'var(--text-secondary)', border: tab === t.key ? `1px solid ${t.color}30` : '1px solid transparent' }}>
            {t.label}
            <span className="ml-2 text-sm font-mono opacity-60">{t.key === 'A' ? stats.A : t.key === 'B' ? stats.B : stats.C}</span>
          </button>
        ))}
      </div>

      {/* 消息列表 */}
      <div ref={listRef} className="space-y-4 pb-8">
        {messages.length === 0 ? (
          <div className="glass rounded-2xl p-16 text-center">
            <Activity size={48} style={{ color: 'var(--text-dim)' }} className="mx-auto mb-4" />
            <p className="text-base" style={{ color: 'var(--text-secondary)' }}>{viewMode === 'bookmarks' ? '暂无收藏消息' : `暂无${CAT[tab].label}数据`}</p>
            <p className="text-sm mt-1 font-mono" style={{ color: 'var(--text-dim)' }}>{viewMode === 'bookmarks' ? '点击星标图标即可收藏' : '等待 scraper.py 采集...'}</p>
          </div>
        ) : messages.map(msg => (
          <MessageCard key={msg.id || msg.msg_id} msg={msg} selected={selectedIds.has(msg.id)}
            onSelect={toggleSelect} onDelete={handleDelete} onBookmark={handleBookmark} />
        ))}
      </div>

      {toast && <Toast message={toast} onDone={() => setToast(null)} />}
    </div>
  );
}
