import { useState, useEffect } from 'react';
import { Cpu, Bell, Palette, Save, Check, Loader2 } from 'lucide-react';

const tabs = [
  { key: 'llm', label: 'LLM 配置', icon: Cpu },
  { key: 'notify', label: '通知设置', icon: Bell },
  { key: 'theme', label: '主题外观', icon: Palette },
];

type ThemeKey = 'cyber' | 'classic';

const THEMES: Record<ThemeKey, { name: string; colors: string[] }> = {
  cyber: { name: '赛博深色', colors: ['#00F2FF', '#BB00FF', '#ADFF00', '#FF5C00'] },
  classic: { name: '经典暗色', colors: ['#818CF8', '#A78BFA', '#34D399', '#FB923C'] },
};

function getSavedTheme(): ThemeKey {
  try { return (localStorage.getItem('theme') as ThemeKey) || 'cyber'; } catch { return 'cyber'; }
}

export default function SettingsPage() {
  const [activeTab, setActiveTab] = useState('llm');
  const [config, setConfig] = useState<any>({});
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [loading, setLoading] = useState(true);
  const [theme, setTheme] = useState<ThemeKey>(getSavedTheme);

  useEffect(() => {
    fetch('/api/config').then(r => r.json()).then(setConfig).finally(() => setLoading(false));
  }, []);

  const saveConfig = async () => {
    setSaving(true);
    try {
      await fetch('/api/config', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          llm_api_key: config.llm_api_key,
          llm_base_url: config.llm_base_url,
          llm_model: config.llm_model,
        }),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch {}
    setSaving(false);
  };

  const switchTheme = (t: ThemeKey) => {
    setTheme(t);
    document.documentElement.setAttribute('data-theme', t);
    try { localStorage.setItem('theme', t); } catch {}
  };

  const update = (key: string, val: any) => {
    setConfig((prev: any) => ({ ...prev, [key]: val }));
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-full">
        <Loader2 size={32} className="animate-spin" style={{ color: 'var(--neon-cyan)' }} />
      </div>
    );
  }

  return (
    <div style={{ padding: '32px 40px 32px 32px' }} className="animate-fade-in">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: 'var(--text-primary)' }}>设置</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>配置系统参数和偏好</p>
        </div>
        <button onClick={saveConfig} disabled={saving}
          className="flex items-center gap-2 px-5 py-2.5 rounded-xl text-sm font-medium transition-all hover:brightness-110 disabled:opacity-50"
          style={{ background: saved ? 'rgba(173,255,0,0.1)' : 'rgba(0,242,255,0.1)', color: saved ? 'var(--neon-green)' : 'var(--neon-cyan)', border: `1px solid ${saved ? 'rgba(173,255,0,0.2)' : 'rgba(0,242,255,0.2)'}` }}>
          {saved ? <><Check size={16} /> 已保存</> : saving ? <><Loader2 size={16} className="animate-spin" /> 保存中...</> : <><Save size={16} /> 保存设置</>}
        </button>
      </div>

      <div className="flex gap-6">
        <div className="w-48 shrink-0">
          <div className="glass rounded-2xl overflow-hidden py-2">
            {tabs.map(tab => {
              const Icon = tab.icon;
              const active = activeTab === tab.key;
              return (
                <button key={tab.key} onClick={() => setActiveTab(tab.key)}
                  className={`w-full flex items-center gap-3 px-4 py-3 text-sm font-medium transition-colors ${active ? '' : 'hover:bg-white/[0.03]'}`}
                  style={{ color: active ? 'var(--neon-cyan)' : 'var(--text-secondary)', background: active ? 'rgba(0,242,255,0.06)' : 'transparent' }}>
                  <Icon size={18} /> {tab.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="flex-1">
          <div className="glass rounded-2xl p-6 space-y-6">
            {activeTab === 'llm' && (
              <>
                <h3 className="text-base font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>LLM 模型配置</h3>
                <Field label="API 基础 URL" value={config.llm_base_url || ''} onChange={v => update('llm_base_url', v)} placeholder="https://api.deepseek.com" />
                <Field label="API Key" value={config.llm_api_key || ''} onChange={v => update('llm_api_key', v)} placeholder="sk-..." type="password" />
                <Field label="模型名称" value={config.llm_model || ''} onChange={v => update('llm_model', v)} placeholder="deepseek-chat" />
                <div className="pt-2">
                  <p className="text-xs" style={{ color: 'var(--text-dim)' }}>支持 OpenAI 兼容接口（DeepSeek / Moonshot / 通义千问等）</p>
                </div>
              </>
            )}

            {activeTab === 'notify' && (
              <>
                <h3 className="text-base font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>通知推送</h3>
                <div className="flex items-center gap-3 px-4 py-6 rounded-xl" style={{ background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)' }}>
                  <Bell size={20} style={{ color: 'var(--text-dim)' }} />
                  <div>
                    <p className="text-sm font-medium" style={{ color: 'var(--text-secondary)' }}>通知功能开发中</p>
                    <p className="text-xs mt-0.5" style={{ color: 'var(--text-dim)' }}>飞书 Webhook 已在设置页面底部的配置中支持，桌面通知即将推出</p>
                  </div>
                </div>
              </>
            )}

            {activeTab === 'theme' && (
              <>
                <h3 className="text-base font-semibold mb-4" style={{ color: 'var(--text-primary)' }}>主题外观</h3>
                <div className="grid grid-cols-2 gap-4">
                  {(Object.keys(THEMES) as ThemeKey[]).map(key => (
                    <ThemeCard
                      key={key}
                      name={THEMES[key].name}
                      active={theme === key}
                      colors={THEMES[key].colors}
                      onClick={() => switchTheme(key)}
                    />
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, value, onChange, placeholder, type = 'text' }: {
  label: string; value: string; onChange: (v: string) => void; placeholder?: string; type?: string;
}) {
  return (
    <div>
      <label className="block text-sm font-medium mb-1.5" style={{ color: 'var(--text-secondary)' }}>{label}</label>
      <input type={type} value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        className="w-full px-4 py-2.5 rounded-xl text-sm outline-none transition-colors"
        style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid var(--border)', color: 'var(--text-primary)' }} />
    </div>
  );
}

function ThemeCard({ name, active, colors, onClick }: { name: string; active: boolean; colors: string[]; onClick?: () => void }) {
  return (
    <div className="rounded-xl p-4 cursor-pointer transition-all"
         onClick={onClick}
         style={{ border: active ? '1px solid rgba(0,242,255,0.3)' : '1px solid var(--border)', background: active ? 'rgba(0,242,255,0.04)' : 'transparent' }}>
      <div className="flex gap-1.5 mb-3">
        {colors.map((c, i) => <div key={i} className="w-5 h-5 rounded-full" style={{ background: c }} />)}
      </div>
      <p className="text-sm font-medium" style={{ color: active ? 'var(--neon-cyan)' : 'var(--text-secondary)' }}>{name}</p>
    </div>
  );
}
