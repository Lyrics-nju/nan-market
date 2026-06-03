import { useState, useEffect, useCallback } from 'react';
import {
  Shield, BookOpen, ShoppingBag, Activity, Wifi, WifiOff,
  MessageSquare, TrendingUp, Clock,
} from 'lucide-react';

interface Stats { total: number; A: number; B: number; C: number; }

const CAT = {
  A: { label: '重要信息', color: '#BB00FF', icon: Shield },
  B: { label: '校园轶事', color: '#ADFF00', icon: BookOpen },
  C: { label: '二手资讯', color: '#FF5C00', icon: ShoppingBag },
};

function StatCard({ cat, count, total }: { cat: keyof typeof CAT; count: number; total: number }) {
  const c = CAT[cat];
  const Icon = c.icon;
  const pct = total > 0 ? Math.round(count / total * 100) : 0;
  return (
    <div className="glass rounded-2xl p-6 relative overflow-hidden">
      <div className="absolute top-0 left-0 w-full h-1" style={{ background: c.color }} />
      <div className="flex items-start justify-between mb-4">
        <div className="w-12 h-12 rounded-xl flex items-center justify-center"
             style={{ background: `${c.color}12` }}>
          <Icon size={24} style={{ color: c.color }} />
        </div>
        <span className="text-xs font-mono px-2 py-1 rounded-lg"
              style={{ background: `${c.color}10`, color: c.color }}>
          {pct}%
        </span>
      </div>
      <p className="text-3xl font-bold mb-1" style={{ color: c.color }}>{count}</p>
      <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>{c.label}</p>
      <div className="mt-3 h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.04)' }}>
        <div className="h-full rounded-full transition-all duration-500"
             style={{ width: `${pct}%`, background: c.color }} />
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats>({ total: 0, A: 0, B: 0, C: 0 });
  const [connected, setConnected] = useState(false);
  const [recentMsgs, setRecentMsgs] = useState<any[]>([]);
  const [services, setServices] = useState<any>({});

  const fetchStats = useCallback(async () => {
    try {
      const res = await fetch('/api/stats');
      setStats(await res.json());
    } catch {}
  }, []);

  useEffect(() => { fetchStats(); }, [fetchStats]);

  useEffect(() => {
    const check = () => fetch('/api/services').then(r => r.json()).then(setServices).catch(() => {});
    check();
    const iv = setInterval(check, 5000);
    return () => clearInterval(iv);
  }, []);

  useEffect(() => {
    const es = new EventSource('/api/stream');
    es.onopen = () => setConnected(true);
    es.onerror = () => setConnected(false);
    es.onmessage = (e) => {
      try {
        const evt = JSON.parse(e.data);
        if (evt.type === 'new_message') {
          const m = evt.data;
          setStats(prev => ({
            total: prev.total + 1,
            A: prev.A + (m.category === 'A' ? 1 : 0),
            B: prev.B + (m.category === 'B' ? 1 : 0),
            C: prev.C + (m.category === 'C' ? 1 : 0),
          }));
          setRecentMsgs(prev => [m, ...prev].slice(0, 10));
        }
      } catch {}
    };
    return () => es.close();
  }, []);

  useEffect(() => {
    fetch('/api/messages?limit=10').then(r => r.json()).then(setRecentMsgs).catch(() => {});
  }, []);

  return (
    <div style={{ padding: '32px 40px 32px 32px' }}>
      {/* 头部 */}
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>仪表盘</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>实时监控社群情报动态</p>
        </div>
        <div className="flex items-center gap-2 px-4 py-2 rounded-xl"
             style={{ background: connected ? 'rgba(0, 242, 255, 0.06)' : 'rgba(255, 92, 0, 0.06)' }}>
          {connected
            ? <><Wifi size={16} style={{ color: 'var(--neon-cyan)' }} /><span className="text-sm font-mono" style={{ color: 'var(--neon-cyan)' }}>LIVE</span></>
            : <><WifiOff size={16} style={{ color: 'var(--neon-orange)' }} /><span className="text-sm font-mono" style={{ color: 'var(--neon-orange)' }}>OFFLINE</span></>
          }
        </div>
      </div>

      {/* 总消息 */}
      <div className="glass rounded-2xl p-8 mb-6 relative overflow-hidden">
        <div className="absolute top-0 left-0 w-full h-1" style={{ background: 'linear-gradient(90deg, #00F2FF, #BB00FF, #ADFF00, #FF5C00)' }} />
        <div className="flex items-center gap-6">
          <div className="w-16 h-16 rounded-2xl flex items-center justify-center"
               style={{ background: 'rgba(0, 242, 255, 0.08)' }}>
            <MessageSquare size={32} style={{ color: 'var(--neon-cyan)' }} />
          </div>
          <div>
            <p className="text-4xl font-bold" style={{ color: 'var(--neon-cyan)' }}>{stats.total}</p>
            <p className="text-base" style={{ color: 'var(--text-secondary)' }}>总消息数</p>
          </div>
          <div className="flex-1" />
          <div className="flex items-center gap-6 text-center">
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <TrendingUp size={14} style={{ color: 'var(--neon-green)' }} />
                <span className="text-sm font-mono" style={{ color: 'var(--neon-green)' }}>活跃</span>
              </div>
              <p className="text-xs" style={{ color: 'var(--text-dim)' }}>实时监控中</p>
            </div>
            <div>
              <div className="flex items-center gap-1.5 mb-1">
                <Clock size={14} style={{ color: 'var(--text-secondary)' }} />
                <span className="text-sm font-mono" style={{ color: 'var(--text-secondary)' }}>最近</span>
              </div>
              <p className="text-xs" style={{ color: 'var(--text-dim)' }}>{recentMsgs.length > 0 ? recentMsgs[0]?.created_at?.slice(11, 16) : '--:--'}</p>
            </div>
          </div>
        </div>
      </div>

      {/* 分类统计 */}
      <div className="grid grid-cols-3 gap-5 mb-6">
        <StatCard cat="A" count={stats.A} total={stats.total} />
        <StatCard cat="B" count={stats.B} total={stats.total} />
        <StatCard cat="C" count={stats.C} total={stats.total} />
      </div>

      {/* 服务状态 */}
      <div className="flex items-center gap-3 mb-6 px-4 py-3 rounded-xl flex-wrap"
           style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)' }}>
        <span className="text-xs font-mono" style={{ color: 'var(--text-dim)' }}>服务状态:</span>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full" style={{ background: services.napcat_webui ? 'var(--neon-green)' : '#FF3333' }} />
          <span className="text-xs font-mono" style={{ color: services.napcat_webui ? 'var(--neon-green)' : '#FF3333' }}>NapCat</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full" style={{ background: services.napcat_ws ? 'var(--neon-green)' : '#FF3333' }} />
          <span className="text-xs font-mono" style={{ color: services.napcat_ws ? 'var(--neon-green)' : '#FF3333' }}>WS 消息通道</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="w-2 h-2 rounded-full" style={{ background: services.llm_configured ? 'var(--neon-green)' : 'var(--neon-orange)' }} />
          <span className="text-xs font-mono" style={{ color: services.llm_configured ? 'var(--neon-green)' : 'var(--neon-orange)' }}>
            LLM: {services.llm_model || '未配置'}
          </span>
        </div>
        {!services.llm_configured && (
          <span className="text-xs font-mono ml-1" style={{ color: 'var(--neon-orange)' }}>
            （使用规则引擎降级）
          </span>
        )}
        {!services.napcat_ws && services.napcat_webui && (
          <span className="text-xs font-mono ml-1" style={{ color: 'var(--neon-orange)' }}>
            ⚠ WS 通道未就绪
          </span>
        )}
      </div>

      {/* 最近消息 */}
      <div className="glass rounded-2xl overflow-hidden">
        <div className="px-6 py-4 flex items-center gap-2" style={{ borderBottom: '1px solid var(--border)' }}>
          <Activity size={18} style={{ color: 'var(--neon-cyan)' }} />
          <h2 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>最新消息</h2>
          <span className="text-xs font-mono px-2 py-0.5 rounded ml-auto"
                style={{ background: 'rgba(0,242,255,0.06)', color: 'var(--text-dim)' }}>
            {recentMsgs.length} 条
          </span>
        </div>
        <div className="divide-y" style={{ borderColor: 'var(--border)' }}>
          {recentMsgs.length === 0 ? (
            <div className="px-6 py-12 text-center">
              <Activity size={32} style={{ color: 'var(--text-dim)' }} className="mx-auto mb-3" />
              <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>暂无消息</p>
              <p className="text-xs mt-1" style={{ color: 'var(--text-dim)' }}>等待 scraper.py 采集...</p>
            </div>
          ) : recentMsgs.map((msg: any, i: number) => {
            const c = CAT[msg.category as keyof typeof CAT] || CAT.A;
            return (
              <div key={msg.id || i} className="px-6 py-4 flex items-start gap-4 hover:bg-white/[0.02] transition-colors">
                <div className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0"
                     style={{ background: `${c.color}12` }}>
                  <c.icon size={18} style={{ color: c.color }} />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium mb-1 truncate" style={{ color: 'var(--neon-cyan)' }}>
                    {msg.summary}
                  </p>
                  <div className="flex items-center gap-3 text-xs" style={{ color: 'var(--text-dim)' }}>
                    <span>{msg.group_name || '未知群'}</span>
                    <span>{msg.sender_name}</span>
                    <span className="font-mono">{msg.created_at?.slice(5, 16)}</span>
                  </div>
                </div>
                <span className="text-xs font-mono px-2 py-0.5 rounded shrink-0"
                      style={{ background: `${c.color}10`, color: c.color }}>
                  {c.label}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
